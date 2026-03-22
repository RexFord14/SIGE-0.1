"""Seed demo data for SIGE — run once after init_db()"""
from database import db, init_db
from crypto import encrypt
from werkzeug.security import generate_password_hash
import datetime

def seed():
    init_db()
    with db() as conn:
        # School year
        conn.execute("INSERT OR IGNORE INTO school_years(name,start_date,end_date,active) VALUES('2024-2025','2024-09-16','2025-07-15',1)")
        sy = conn.execute("SELECT id FROM school_years WHERE active=1").fetchone()
        if not sy:
            return
        sy_id = sy["id"]

        # Lapsos
        for name, start, end in [
            ("Lapso 1","2024-09-16","2024-12-13"),
            ("Lapso 2","2025-01-13","2025-03-28"),
            ("Lapso 3","2025-03-31","2025-07-15"),
        ]:
            conn.execute("INSERT OR IGNORE INTO lapsos(school_year_id,name,start_date,end_date,active) VALUES(?,?,?,?,1)",
                (sy_id, name, start, end))

        # Courses
        for name, level, grade in [
            ("1er Año","SECONDARY",1),("2do Año","SECONDARY",2),
            ("3er Año","SECONDARY",3),("4to Año","SECONDARY",4),
            ("5to Año","SECONDARY",5),
        ]:
            conn.execute("INSERT OR IGNORE INTO courses(name,level,grade) VALUES(?,?,?)",(name,level,grade))

        c1 = conn.execute("SELECT id FROM courses WHERE grade=1").fetchone()["id"]
        c2 = conn.execute("SELECT id FROM courses WHERE grade=2").fetchone()["id"]

        # Sections
        for course_id, sec_name in [(c1,"A"),(c1,"B"),(c2,"A")]:
            conn.execute("INSERT OR IGNORE INTO sections(course_id,school_year_id,name,max_capacity) VALUES(?,?,?,30)",
                (course_id, sy_id, sec_name))

        sec1 = conn.execute("SELECT id FROM sections WHERE course_id=? AND name='A'", (c1,)).fetchone()["id"]

        # Subjects
        for subj, course_id in [
            ("Matemáticas",c1),("Castellano",c1),("Física",c1),("Química",c1),("Historia",c1),
            ("Matemáticas",c2),("Castellano",c2),("Biología",c2),
        ]:
            conn.execute("INSERT OR IGNORE INTO subjects(name,course_id) VALUES(?,?)",(subj,course_id))

        # Evaluation config
        conn.execute("INSERT OR IGNORE INTO evaluation_config(school_year_id,min_passing_grade,max_grade,use_decimals,rounding_rule) VALUES(?,10.0,20.0,1,'ROUND_HALF_UP')",(sy_id,))

        # Activity types for lapso 1 + Matemáticas
        l1 = conn.execute("SELECT id FROM lapsos WHERE name='Lapso 1' AND school_year_id=?", (sy_id,)).fetchone()
        subj_mat = conn.execute("SELECT id FROM subjects WHERE name='Matemáticas' AND course_id=?", (c1,)).fetchone()
        if l1 and subj_mat:
            for name, weight in [("Evaluación",40),("Tarea",30),("Proyecto",30)]:
                conn.execute("INSERT OR IGNORE INTO activity_types(name,weight,lapso_id,subject_id) VALUES(?,?,?,?)",
                    (name, weight, l1["id"], subj_mat["id"]))

        # Fee concepts
        for name, amount in [("Mensualidad",150.0),("Inscripción",300.0),("Transporte",80.0),("Seguro Escolar",50.0)]:
            conn.execute("INSERT OR IGNORE INTO fee_concepts(name,amount,recurrent) VALUES(?,?,1)",(name,amount))

        # Representatives and students
        students_data = [
            ("Ana","García","2010-03-15","F","V-25111001","María García","V-10111001","Madre","0414-1234567","ana@email.com"),
            ("Carlos","Rodríguez","2010-07-22","M","V-25111002","Pedro Rodríguez","V-10111002","Padre","0424-7654321","pedro@email.com"),
            ("Laura","Martínez","2010-11-08","F","V-25111003","Rosa Martínez","V-10111003","Madre","0416-9876543","rosa@email.com"),
            ("Miguel","Hernández","2009-05-30","M","V-25111004","Juan Hernández","V-10111004","Padre","0412-3456789","juan@email.com"),
            ("Sofía","López","2010-02-14","F","V-25111005","Carmen López","V-10111005","Madre","0426-8765432","carmen@email.com"),
        ]
        for fn, ln, bd, gender, ced, rep_name, rep_ced, rel, phone, email in students_data:
            rep_enc = encrypt(rep_ced)
            rep = conn.execute("SELECT id FROM representatives WHERE cedula_enc=?", (rep_enc,)).fetchone()
            if not rep:
                conn.execute("INSERT INTO representatives(cedula_enc,full_name,phone_enc,email_enc,relationship) VALUES(?,?,?,?,?)",
                    (rep_enc, rep_name, encrypt(phone), encrypt(email), rel))
                rep_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                rep_id = rep["id"]
            ced_enc = encrypt(ced)
            existing = conn.execute("SELECT id FROM students WHERE cedula_enc=?", (ced_enc,)).fetchone()
            if not existing:
                conn.execute("INSERT INTO students(cedula_enc,first_name,last_name,birth_date,gender,section_id,representative_id,status) VALUES(?,?,?,?,?,?,?,'ACTIVO')",
                    (ced_enc, fn, ln, bd, gender, sec1, rep_id))

        # Demo invoices + payments
        students = conn.execute("SELECT id FROM students LIMIT 3").fetchall()
        concept = conn.execute("SELECT id FROM fee_concepts WHERE name='Mensualidad'").fetchone()
        uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        if concept:
            for i, s in enumerate(students):
                inv_num = f"FAC-{i+1:06d}"
                existing = conn.execute("SELECT id FROM invoices WHERE invoice_number=?", (inv_num,)).fetchone()
                if not existing:
                    conn.execute("INSERT INTO invoices(invoice_number,student_id,concept_id,amount,net_amount,due_date,school_year_id,created_by) VALUES(?,?,?,150,150,'2025-01-31',?,?)",
                        (inv_num, s["id"], concept["id"], sy_id, uid))
            # One paid invoice
            inv1 = conn.execute("SELECT id FROM invoices WHERE invoice_number='FAC-000001'").fetchone()
            if inv1:
                pay_existing = conn.execute("SELECT id FROM payments WHERE payment_number='PAG-000001'").fetchone()
                if not pay_existing:
                    conn.execute("INSERT INTO payments(payment_number,invoice_id,amount,payment_method,payment_date,created_by) VALUES('PAG-000001',?,150,'EFECTIVO','2025-01-15',?)",
                        (inv1["id"], uid))
                    conn.execute("UPDATE invoices SET paid_amount=150,status='PAGADO' WHERE id=?", (inv1["id"],))
            # One moroso
            if len(students) >= 2:
                conn.execute("UPDATE students SET status='MOROSO' WHERE id=?", (students[1]["id"],))

        # Open cash register today
        today = datetime.date.today().isoformat()
        conn.execute("INSERT OR IGNORE INTO cash_register(date,opening_amount,total_cash_in,total_transfers,opened_by) VALUES(?,500,150,0,?)",
            (today, uid))

    print("Demo data seeded OK")
    print("  — 5 estudiantes en 1er Año A")
    print("  — 3 facturas (1 pagada, 2 pendientes, 1 moroso)")
    print("  — Caja abierta con Bs. 500 de apertura")
    print("  — Conceptos: Mensualidad, Inscripción, Transporte, Seguro")

if __name__ == "__main__":
    seed()
