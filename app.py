import streamlit as st
import pandas as pd
import sqlite3
from datetime import date, datetime, timedelta
import math
import os
import shutil

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Sistema de Gestión RRHH - Ecuador",
    page_icon="🇪🇨",
    layout="wide"
)

# --- COMPATIBILIDAD STREAMLIT ---
def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# --- BASE DE DATOS ---
DB_NAME = "hr_ecuador.db"
DOCS_DIR = "hr_documentos"

def ensure_dirs():
    os.makedirs(DOCS_DIR, exist_ok=True)

def init_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Áreas
    c.execute('CREATE TABLE IF NOT EXISTS areas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre_area TEXT UNIQUE NOT NULL)')

    # Empleados
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula TEXT UNIQUE NOT NULL,
            nombre_completo TEXT NOT NULL,
            fecha_ingreso DATE NOT NULL,
            fecha_nacimiento DATE,
            salario_base REAL,
            cargo TEXT,
            area_id INTEGER,
            jefe_id INTEGER,
            estado TEXT DEFAULT 'Activo',
            fecha_salida DATE
        )
    ''')
    for col in ["fecha_salida", "fecha_nacimiento"]:
        try:
            c.execute(f"ALTER TABLE employees ADD COLUMN {col} DATE")
        except sqlite3.OperationalError:
            pass

    # Usuarios
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            employee_id INTEGER
        )
    ''')

    # Deadlines manuales
    c.execute('''
        CREATE TABLE IF NOT EXISTS custom_deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            fecha DATE,
            tipo TEXT
        )
    ''')

    # Vacaciones
    c.execute('''
        CREATE TABLE IF NOT EXISTS vacation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula TEXT,
            fecha_inicio DATE,
            fecha_fin DATE,
            dias_tomados INTEGER,
            observacion TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE vacation_logs ADD COLUMN observacion TEXT")
    except sqlite3.OperationalError:
        pass

    # Liquidaciones (auditoría)
    c.execute('''
        CREATE TABLE IF NOT EXISTS liquidation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            nombre_empleado TEXT,
            fecha_salida DATE,
            motivo TEXT,
            sbu_usado REAL,
            salario_base REAL,
            neto REAL,
            registrado_por TEXT,
            fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
            numero_acta TEXT,
            observaciones TEXT
        )
    ''')

    # Documentos de ingreso por empleado
    c.execute('''
        CREATE TABLE IF NOT EXISTS employee_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            tipo_doc TEXT NOT NULL,
            ruta_archivo TEXT,
            fecha_carga DATETIME DEFAULT CURRENT_TIMESTAMP,
            cargado_por TEXT
        )
    ''')

    # Documentos de salida (liquidación)
    c.execute('''
        CREATE TABLE IF NOT EXISTS separation_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            tipo_doc TEXT NOT NULL,
            ruta_archivo TEXT,
            fecha_carga DATETIME DEFAULT CURRENT_TIMESTAMP,
            cargado_por TEXT
        )
    ''')

    # Config
    c.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, sbu_current REAL)')
    c.execute("SELECT COUNT(*) FROM config")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO config (id, sbu_current) VALUES (1, 482.0)")

    # Usuario maestro
    c.execute("SELECT COUNT(*) FROM users WHERE username = 'AlexV26'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password, role) VALUES ('AlexV26', 'Alexvelez007', 'admin')")

    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- LÓGICA DE NEGOCIO ---
def update_sbu(new_value):
    conn = get_db_connection()
    conn.execute("UPDATE config SET sbu_current = ? WHERE id = 1", (new_value,))
    conn.commit()
    conn.close()

def get_sbu():
    conn = get_db_connection()
    row = conn.execute("SELECT sbu_current FROM config WHERE id = 1").fetchone()
    conn.close()
    return row['sbu_current'] if row else 482.0

def get_vacation_balance(cedula, fecha_ingreso):
    if isinstance(fecha_ingreso, str):
        f_ing = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
    else:
        f_ing = fecha_ingreso
    gen = ((date.today() - f_ing).days / 365) * 15
    conn = get_db_connection()
    tom = conn.execute("SELECT SUM(dias_tomados) FROM vacation_logs WHERE cedula = ?", (cedula,)).fetchone()[0] or 0
    conn.close()
    return gen - tom

def save_uploaded_file(uploaded_file, subfolder, filename):
    """Guarda un archivo subido en la carpeta local y retorna la ruta."""
    folder = os.path.join(DOCS_DIR, subfolder)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return filepath

# --- LOGIN ---
def check_login():
    if "authenticated" not in st.session_state:
        st.session_state.update({"authenticated": False, "username": None, "role": None, "user_id": None})

    if not st.session_state["authenticated"]:
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            st.title("🇪🇨 Sistema RRHH")
            st.caption("Acceso corporativo")
            with st.form("login_form"):
                u = st.text_input("Usuario")
                p = st.text_input("Contraseña", type="password")
                if st.form_submit_button("Ingresar", use_container_width=True):
                    conn = get_db_connection()
                    user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u, p)).fetchone()
                    conn.close()
                    if user:
                        st.session_state.update({
                            "authenticated": True, "username": u,
                            "role": user['role'], "user_id": user['id']
                        })
                        safe_rerun()
                    else:
                        st.error("Credenciales inválidas.")
        return False
    return True

# --- MAIN ---
def main():
    init_db()
    if not check_login():
        return

    if 'menu_actual' not in st.session_state:
        st.session_state['menu_actual'] = "Calendario Operativo"

    st.sidebar.title(f"👤 {st.session_state['username']}")
    st.sidebar.caption(f"Rol: {st.session_state['role'].upper()}")

    nav_options = [
        "Calendario Operativo",
        "Datos Empleados",
        "Control de Vacaciones",
        "Liquidaciones",
        "Auditoría de Salidas",
    ]
    if st.session_state['role'] == 'admin':
        nav_options.append("Configuración Global")

    try:
        index_actual = nav_options.index(st.session_state['menu_actual'])
    except ValueError:
        index_actual = 0

    menu = st.sidebar.radio("Navegación:", nav_options, index=index_actual)

    if menu != st.session_state['menu_actual']:
        st.session_state['menu_actual'] = menu
        safe_rerun()

    if st.sidebar.button("Cerrar Sesión"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        safe_rerun()

    # ==========================================
    # MÓDULO: CALENDARIO OPERATIVO
    # ==========================================
    if menu == "Calendario Operativo":
        st.title("📅 Calendario de Cumplimiento Operativo")
        today = date.today()
        year = today.year

        with st.expander("➕ Agregar Deadline Manual"):
            with st.form("new_deadline"):
                t = st.text_input("Descripción de la tarea")
                f = st.date_input("Fecha límite")
                tipo = st.selectbox("Categoría", ["IESS", "SUT", "Contratos", "Décimos", "Utilidades", "Otros"])
                if st.form_submit_button("Guardar"):
                    conn = get_db_connection()
                    conn.execute("INSERT INTO custom_deadlines (titulo, fecha, tipo) VALUES (?,?,?)", (t, str(f), tipo))
                    conn.commit()
                    conn.close()
                    st.success("Deadline agregado.")
                    safe_rerun()

        conn = get_db_connection()
        ingresos = pd.read_sql_query("SELECT nombre_completo, fecha_ingreso FROM employees WHERE estado='Activo'", conn)
        salidas = pd.read_sql_query("SELECT nombre_completo, fecha_salida FROM employees WHERE estado='Inactivo' AND fecha_salida IS NOT NULL", conn)
        manuales = pd.read_sql_query("SELECT * FROM custom_deadlines ORDER BY fecha ASC", conn)
        conn.close()

        eventos = []

        # Eventos legales fijos anuales
        eventos_fijos = [
            {"Fecha": date(year, today.month, 10), "Tarea": "🔴 Pago Aportes IESS", "Link": None, "Tipo": "IESS"},
            {"Fecha": date(year, today.month, 20), "Tarea": "🟡 Cierre de Nómina", "Link": None, "Tipo": "Nómina"},
            {"Fecha": date(year, 3, 15), "Tarea": "🟢 Pago Décimo Cuarto", "Link": None, "Tipo": "Décimo"},
            {"Fecha": date(year, 12, 24), "Tarea": "🟢 Pago Décimo Tercero", "Link": None, "Tipo": "Décimo"},
            {"Fecha": date(year, 4, 15), "Tarea": "🔴 Pago Utilidades", "Link": None, "Tipo": "Utilidades"},
        ]
        for ev in eventos_fijos:
            if ev["Fecha"] >= today:
                eventos.append(ev)

        # Dinámicos: ingresos (+7 días para SUT)
        for _, row in ingresos.iterrows():
            f_limite = datetime.strptime(row['fecha_ingreso'], '%Y-%m-%d').date() + timedelta(days=7)
            diff = (f_limite - today).days
            icono = "🔴" if diff < 0 else ("🟡" if diff <= 5 else "🟢")
            if f_limite >= today:
                eventos.append({
                    "Fecha": f_limite,
                    "Tarea": f"{icono} SUT: {row['nombre_completo']}",
                    "Link": "Datos Empleados",
                    "Tipo": "SUT"
                })

        # Dinámicos: salidas (+7 días para liquidación)
        for _, row in salidas.iterrows():
            if row['fecha_salida']:
                f_limite = datetime.strptime(row['fecha_salida'], '%Y-%m-%d').date() + timedelta(days=7)
                if f_limite >= today:
                    eventos.append({
                        "Fecha": f_limite,
                        "Tarea": f"🔴 Cargar liquidación: {row['nombre_completo']}",
                        "Link": "Auditoría de Salidas",
                        "Tipo": "Liquidación"
                    })

        # Manuales
        for _, row in manuales.iterrows():
            f_limite = datetime.strptime(row['fecha'], '%Y-%m-%d').date()
            if f_limite >= today:
                eventos.append({
                    "Fecha": f_limite,
                    "Tarea": f"🟡 {row['tipo']}: {row['titulo']}",
                    "Link": None,
                    "Tipo": row['tipo']
                })

        st.subheader(f"Pendientes a partir de hoy — {today.strftime('%d/%m/%Y')}")

        if not eventos:
            st.info("No hay tareas pendientes.")
        else:
            eventos_sorted = sorted(eventos, key=lambda x: x['Fecha'])
            for ev in eventos_sorted:
                diff = (ev['Fecha'] - today).days
                if diff == 0:
                    urgencia = "🔴 HOY"
                elif diff <= 3:
                    urgencia = f"🟠 En {diff} días"
                elif diff <= 7:
                    urgencia = f"🟡 En {diff} días"
                else:
                    urgencia = f"🟢 En {diff} días"

                col1, col2, col3, col4 = st.columns([1.2, 3, 1, 1])
                with col1:
                    st.info(ev['Fecha'].strftime('%d %b %Y'))
                with col2:
                    st.markdown(f"**{ev['Tarea']}**")
                with col3:
                    st.caption(urgencia)
                with col4:
                    if ev.get('Link'):
                        if st.button("Ir →", key=f"btn_{ev['Tarea']}_{ev['Fecha']}"):
                            st.session_state['menu_actual'] = ev['Link']
                            safe_rerun()

        # Gestión de deadlines manuales
        if not manuales.empty:
            st.divider()
            st.subheader("Deadlines manuales guardados")
            for _, row in manuales.iterrows():
                col1, col2, col3 = st.columns([3, 1, 0.5])
                with col1:
                    st.text(f"{row['tipo']}: {row['titulo']} — {row['fecha']}")
                with col3:
                    if st.button("🗑️", key=f"del_dl_{row['id']}"):
                        conn = get_db_connection()
                        conn.execute("DELETE FROM custom_deadlines WHERE id = ?", (row['id'],))
                        conn.commit()
                        conn.close()
                        safe_rerun()

    # ==========================================
    # MÓDULO: DATOS EMPLEADOS
    # ==========================================
    elif menu == "Datos Empleados":
        st.title("👥 Gestión de Talento")

        conn = get_db_connection()
        areas = pd.read_sql_query("SELECT * FROM areas", conn)
        jefes = pd.read_sql_query("SELECT id, nombre_completo FROM employees WHERE estado='Activo'", conn)
        listado = pd.read_sql_query(
            "SELECT e.*, a.nombre_area FROM employees e LEFT JOIN areas a ON e.area_id = a.id",
            conn
        )
        conn.close()

        tab1, tab2, tab3 = st.tabs(["📋 Listado", "➕ Nuevo Colaborador", "📁 Expediente Digital"])

        # --- TAB 1: LISTADO Y EDICIÓN ---
        with tab1:
            st.subheader("Personal registrado")
            filtro = st.selectbox("Filtrar por estado", ["Activo", "Inactivo", "Todos"])
            if filtro != "Todos":
                df_show = listado[listado['estado'] == filtro]
            else:
                df_show = listado

            st.dataframe(df_show[['cedula','nombre_completo','cargo','nombre_area','fecha_ingreso','salario_base','estado']],
                         use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("✏️ Editar datos de un colaborador")
            if not df_show.empty:
                nombres = df_show['nombre_completo'].tolist()
                sel_nombre = st.selectbox("Seleccionar empleado para editar", nombres)
                emp_edit = df_show[df_show['nombre_completo'] == sel_nombre].iloc[0]

                with st.form("edit_emp"):
                    c1, c2 = st.columns(2)
                    new_nombre = c1.text_input("Nombre completo", value=emp_edit['nombre_completo'])
                    new_cargo = c1.text_input("Cargo", value=emp_edit['cargo'] or "")
                    new_sal = c2.number_input("Salario base", value=float(emp_edit['salario_base'] or get_sbu()))
                    new_estado = c2.selectbox("Estado", ["Activo", "Inactivo"],
                                              index=0 if emp_edit['estado'] == 'Activo' else 1)

                    area_opt = {r['nombre_area']: r['id'] for _, r in areas.iterrows()}
                    area_actual = emp_edit['nombre_area'] if emp_edit['nombre_area'] in area_opt else (list(area_opt.keys())[0] if area_opt else None)
                    ar_sel = c1.selectbox("Área", list(area_opt.keys()),
                                          index=list(area_opt.keys()).index(area_actual) if area_actual else 0) if area_opt else None

                    if st.form_submit_button("💾 Guardar cambios"):
                        conn = get_db_connection()
                        conn.execute(
                            "UPDATE employees SET nombre_completo=?, cargo=?, salario_base=?, estado=?, area_id=? WHERE id=?",
                            (new_nombre, new_cargo, new_sal, new_estado,
                             area_opt[ar_sel] if ar_sel else None, int(emp_edit['id']))
                        )
                        conn.commit()
                        conn.close()
                        st.success("✅ Datos actualizados correctamente.")
                        safe_rerun()

        # --- TAB 2: NUEVO COLABORADOR ---
        with tab2:
            if st.session_state['role'] == 'admin':
                with st.form("add_emp"):
                    c1, c2 = st.columns(2)
                    ced = c1.text_input("Cédula")
                    nom = c1.text_input("Nombre Completo")
                    car = c1.text_input("Cargo")
                    f_ing = c1.date_input("Fecha de Ingreso")
                    f_nac = c2.date_input("Fecha de Nacimiento", value=date(1990, 1, 1))
                    sal = c2.number_input("Salario", value=get_sbu())
                    area_opt = {r['nombre_area']: r['id'] for _, r in areas.iterrows()}
                    ar_sel = c2.selectbox("Área", list(area_opt.keys())) if area_opt else None
                    jf_opt = {r['nombre_completo']: r['id'] for _, r in jefes.iterrows()}
                    jf_sel = c2.selectbox("Jefe Inmediato", ["Ninguno"] + list(jf_opt.keys()))

                    if st.form_submit_button("Guardar"):
                        if not ced or not nom:
                            st.error("Cédula y nombre son obligatorios.")
                        else:
                            conn = get_db_connection()
                            j_id = jf_opt.get(jf_sel) if jf_sel != "Ninguno" else None
                            try:
                                conn.execute(
                                    "INSERT INTO employees (cedula, nombre_completo, fecha_ingreso, fecha_nacimiento, salario_base, cargo, area_id, jefe_id) VALUES (?,?,?,?,?,?,?,?)",
                                    (ced, nom, str(f_ing), str(f_nac), sal, car,
                                     area_opt[ar_sel] if ar_sel else None, j_id)
                                )
                                conn.commit()
                                st.success(f"✅ {nom} registrado correctamente.")
                            except sqlite3.IntegrityError:
                                st.error("Ya existe un empleado con esa cédula.")
                            finally:
                                conn.close()
                            safe_rerun()
            else:
                st.info("Solo administradores pueden registrar colaboradores.")

        # --- TAB 3: EXPEDIENTE DIGITAL ---
        with tab3:
            st.subheader("📁 Documentos de ingreso por colaborador")
            st.caption("Sube los documentos requeridos para cada empleado activo.")

            if listado.empty:
                st.info("No hay empleados registrados.")
            else:
                activos = listado[listado['estado'] == 'Activo']
                if activos.empty:
                    st.info("No hay empleados activos.")
                else:
                    sel_exp = st.selectbox("Seleccionar empleado", activos['nombre_completo'].tolist(), key="exp_sel")
                    emp_exp = activos[activos['nombre_completo'] == sel_exp].iloc[0]
                    emp_id = int(emp_exp['id'])
                    cedula = emp_exp['cedula']

                    # Los 3 documentos requeridos de ingreso
                    docs_requeridos = [
                        ("contrato_firmado", "1. Contrato Firmado"),
                        ("aviso_entrada", "2. Aviso de Entrada"),
                        ("cedula_licencia", "3. Copia de Cédula y Licencia"),
                    ]

                    conn = get_db_connection()
                    docs_cargados = pd.read_sql_query(
                        "SELECT * FROM employee_documents WHERE employee_id = ?",
                        conn, params=(emp_id,)
                    )
                    conn.close()

                    st.markdown(f"**Empleado:** {sel_exp} — Cédula: `{cedula}`")
                    st.divider()

                    for tipo_key, tipo_label in docs_requeridos:
                        doc_existente = docs_cargados[docs_cargados['tipo_doc'] == tipo_key]
                        col1, col2, col3 = st.columns([2.5, 2, 1])
                        with col1:
                            st.markdown(f"**{tipo_label}**")
                        with col2:
                            if not doc_existente.empty:
                                fecha_c = doc_existente.iloc[0]['fecha_carga']
                                st.success(f"✅ Cargado — {fecha_c[:10] if fecha_c else ''}")
                            else:
                                st.warning("⏳ Pendiente")
                        with col3:
                            uploaded = st.file_uploader(
                                "Subir", key=f"upload_{emp_id}_{tipo_key}",
                                label_visibility="collapsed",
                                type=["pdf", "jpg", "jpeg", "png"]
                            )
                            if uploaded:
                                filename = f"{cedula}_{tipo_key}_{date.today()}.{uploaded.name.split('.')[-1]}"
                                ruta = save_uploaded_file(uploaded, f"ingreso_{cedula}", filename)
                                conn = get_db_connection()
                                # Reemplazar si ya existía
                                conn.execute("DELETE FROM employee_documents WHERE employee_id=? AND tipo_doc=?", (emp_id, tipo_key))
                                conn.execute(
                                    "INSERT INTO employee_documents (employee_id, tipo_doc, ruta_archivo, cargado_por) VALUES (?,?,?,?)",
                                    (emp_id, tipo_key, ruta, st.session_state['username'])
                                )
                                conn.commit()
                                conn.close()
                                st.success("Guardado.")
                                safe_rerun()

    # ==========================================
    # MÓDULO: CONTROL DE VACACIONES
    # ==========================================
    elif menu == "Control de Vacaciones":
        st.title("🌴 Control de Vacaciones")

        conn = get_db_connection()
        emps = pd.read_sql_query(
            "SELECT cedula, nombre_completo, fecha_ingreso FROM employees WHERE estado='Activo'",
            conn
        )
        conn.close()

        if emps.empty:
            st.info("No hay empleados activos.")
        else:
            sel = st.selectbox(
                "Empleado",
                [f"{r['nombre_completo']} ({r['cedula']})" for _, r in emps.iterrows()]
            )
            c_sel = sel.split("(")[1].replace(")", "")
            e_dat = emps[emps['cedula'] == c_sel].iloc[0]

            saldo = get_vacation_balance(c_sel, e_dat['fecha_ingreso'])
            col1, col2 = st.columns(2)
            col1.metric("Saldo de Días Disponibles", f"{saldo:.2f} días")
            col2.metric("Empleado", e_dat['nombre_completo'])

            st.divider()

            # Registrar vacaciones
            with st.expander("➕ Registrar período de vacaciones"):
                with st.form("vac_form"):
                    c1, c2 = st.columns(2)
                    f1 = c1.date_input("Fecha inicio")
                    f2 = c2.date_input("Fecha fin")
                    d_auto = (f2 - f1).days + 1 if f2 >= f1 else 0
                    rd = c1.number_input("Días a descontar", value=max(0, d_auto), min_value=0)
                    obs = c2.text_input("Observación (opcional)")
                    if st.form_submit_button("Grabar registro"):
                        if rd <= 0:
                            st.error("Los días deben ser mayor a 0.")
                        elif rd > saldo:
                            st.error(f"No hay saldo suficiente. Saldo actual: {saldo:.2f} días.")
                        else:
                            conn = get_db_connection()
                            conn.execute(
                                "INSERT INTO vacation_logs (cedula, fecha_inicio, fecha_fin, dias_tomados, observacion) VALUES (?,?,?,?,?)",
                                (c_sel, str(f1), str(f2), rd, obs)
                            )
                            conn.commit()
                            conn.close()
                            st.success("✅ Registro de vacaciones guardado.")
                            safe_rerun()

            # Historial con opción de eliminar
            st.subheader("📋 Historial de vacaciones")
            conn = get_db_connection()
            historial = pd.read_sql_query(
                "SELECT * FROM vacation_logs WHERE cedula = ? ORDER BY fecha_inicio DESC",
                conn, params=(c_sel,)
            )
            conn.close()

            if historial.empty:
                st.info("Sin registros de vacaciones para este empleado.")
            else:
                for _, row in historial.iterrows():
                    col1, col2, col3, col4, col5 = st.columns([1.5, 1.5, 1, 2, 0.6])
                    with col1:
                        st.text(f"Inicio: {row['fecha_inicio']}")
                    with col2:
                        st.text(f"Fin: {row['fecha_fin']}")
                    with col3:
                        st.text(f"{row['dias_tomados']} días")
                    with col4:
                        st.caption(row['observacion'] or "—")
                    with col5:
                        if st.button("🗑️", key=f"del_vac_{row['id']}", help="Eliminar este registro"):
                            conn = get_db_connection()
                            conn.execute("DELETE FROM vacation_logs WHERE id = ?", (int(row['id']),))
                            conn.commit()
                            conn.close()
                            st.success("Registro eliminado.")
                            safe_rerun()

    # ==========================================
    # MÓDULO: LIQUIDACIONES
    # ==========================================
    elif menu == "Liquidaciones":
        st.title("💼 Procesamiento de Liquidación")

        conn = get_db_connection()
        emps = pd.read_sql_query("SELECT * FROM employees WHERE estado='Activo'", conn)
        conn.close()

        if emps.empty:
            st.info("Sin personal activo para liquidar.")
        else:
            nom_sel = st.selectbox("Empleado a liquidar", [r['nombre_completo'] for _, r in emps.iterrows()])
            emp = emps[emps['nombre_completo'] == nom_sel].iloc[0]
            sbu = get_sbu()

            st.info(f"📋 **{emp['nombre_completo']}** | Cédula: {emp['cedula']} | Ingreso: {emp['fecha_ingreso']} | Salario: ${emp['salario_base']:.2f}")

            with st.form("calc_liq"):
                c1, c2 = st.columns(2)
                f_sal = c1.date_input("Fecha de Salida", value=date.today())
                motivo = c1.selectbox("Motivo de Salida", ["Renuncia", "Despido Intempestivo", "Acuerdo"])
                num_acta = c2.text_input("Número de Acta (opcional)")
                desc = c2.number_input("Descuentos varios ($)", min_value=0.0, value=0.0)
                obs_liq = c2.text_area("Observaciones", height=80)

                if st.form_submit_button("🧮 Calcular Liquidación"):
                    f_ing = datetime.strptime(emp['fecha_ingreso'], '%Y-%m-%d').date()
                    d_mes = f_sal.day
                    anios = (f_sal - f_ing).days // 365

                    sueldo = (emp['salario_base'] / 30) * d_mes
                    d3 = (emp['salario_base'] / 360) * d_mes
                    d4 = (sbu / 360) * d_mes
                    fr = (emp['salario_base'] * 0.0833 / 30) * d_mes if anios >= 1 else 0

                    bal_vac = get_vacation_balance(emp['cedula'], emp['fecha_ingreso'])
                    v_vac = (emp['salario_base'] / 24) * bal_vac
                    v_des = (emp['salario_base'] * 0.25) * anios

                    v_int = 0
                    if motivo == "Despido Intempestivo":
                        v_int = max(emp['salario_base'] * 3,
                                    emp['salario_base'] * math.ceil((f_sal - f_ing).days / 365))

                    iess = (sueldo + d3 + d4 + fr) * 0.0945
                    neto = (sueldo + d3 + d4 + fr + v_vac + v_des + v_int) - (iess + desc)

                    st.session_state.liq_data = {
                        "id": int(emp['id']),
                        "nombre": emp['nombre_completo'],
                        "cedula": emp['cedula'],
                        "neto": neto,
                        "f_sal": str(f_sal),
                        "motivo": motivo,
                        "num_acta": num_acta,
                        "obs": obs_liq,
                        "sbu": sbu,
                        "salario": float(emp['salario_base']),
                        "resumen": pd.DataFrame([
                            {"Concepto": "Sueldo proporcional", "Valor ($)": round(sueldo, 2)},
                            {"Concepto": "Décimos + Fondo Reserva", "Valor ($)": round(d3 + d4 + fr, 2)},
                            {"Concepto": "Vacaciones no gozadas", "Valor ($)": round(v_vac, 2)},
                            {"Concepto": "Desahucio", "Valor ($)": round(v_des, 2)},
                            {"Concepto": "Indemnización", "Valor ($)": round(v_int, 2)},
                            {"Concepto": "IESS empleado (9.45%)", "Valor ($)": round(-iess, 2)},
                            {"Concepto": "Descuentos varios", "Valor ($)": round(-desc, 2)},
                        ])
                    }

            if "liq_data" in st.session_state and st.session_state.liq_data["id"] == int(emp['id']):
                ld = st.session_state.liq_data
                st.divider()
                st.subheader("Resumen de Liquidación")
                st.table(ld["resumen"])

                col1, col2 = st.columns(2)
                col1.metric("💰 Neto a Recibir", f"${ld['neto']:,.2f}")
                col2.info(f"Motivo: **{ld['motivo']}** | Acta: {ld['num_acta'] or 'N/A'}")

                st.warning("⚠️ Revisa los valores antes de confirmar. Esta acción inactiva al empleado.")

                if st.button("✅ Confirmar Liquidación y Generar Deadline", type="primary"):
                    conn = get_db_connection()
                    # Inactivar empleado CON fecha de salida
                    conn.execute(
                        "UPDATE employees SET estado='Inactivo', fecha_salida=? WHERE id=?",
                        (ld['f_sal'], ld['id'])
                    )
                    # Registrar en auditoría
                    conn.execute(
                        """INSERT INTO liquidation_logs
                        (employee_id, nombre_empleado, fecha_salida, motivo, sbu_usado,
                         salario_base, neto, registrado_por, numero_acta, observaciones)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (ld['id'], ld['nombre'], ld['f_sal'], ld['motivo'],
                         ld['sbu'], ld['salario'], ld['neto'],
                         st.session_state['username'], ld['num_acta'], ld['obs'])
                    )
                    # Deadline en calendario: 7 días para cargar documentos
                    f_deadline = (datetime.strptime(ld['f_sal'], '%Y-%m-%d').date() + timedelta(days=7))
                    conn.execute(
                        "INSERT INTO custom_deadlines (titulo, fecha, tipo) VALUES (?,?,?)",
                        (f"Cargar docs salida: {ld['nombre']}", str(f_deadline), "Liquidación")
                    )
                    conn.commit()
                    conn.close()

                    del st.session_state.liq_data
                    st.success(f"✅ Liquidación de {ld['nombre']} registrada. Deadline generado para {f_deadline.strftime('%d/%m/%Y')}.")
                    st.session_state['menu_actual'] = "Auditoría de Salidas"
                    safe_rerun()

    # ==========================================
    # MÓDULO: AUDITORÍA DE SALIDAS
    # ==========================================
    elif menu == "Auditoría de Salidas":
        st.title("📂 Auditoría de Salidas")

        conn = get_db_connection()
        inactivos = pd.read_sql_query(
            """SELECT e.id, e.cedula, e.nombre_completo, e.fecha_salida,
                      l.motivo, l.neto, l.registrado_por, l.fecha_registro,
                      l.numero_acta, l.observaciones, l.id as log_id
               FROM employees e
               LEFT JOIN liquidation_logs l ON e.id = l.employee_id
               WHERE e.estado = 'Inactivo'
               ORDER BY e.fecha_salida DESC""",
            conn
        )
        conn.close()

        if inactivos.empty:
            st.info("No hay empleados inactivos registrados aún.")
        else:
            st.caption(f"Total de salidas registradas: **{len(inactivos)}**")

            for _, row in inactivos.iterrows():
                with st.expander(f"🔴 {row['nombre_completo']} — Salida: {row['fecha_salida'] or 'N/R'} | {row['motivo'] or 'Sin liquidación registrada'}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Neto Liquidado", f"${row['neto']:,.2f}" if row['neto'] else "N/R")
                    c2.metric("Registrado por", row['registrado_por'] or "N/R")
                    c3.metric("Acta N°", row['numero_acta'] or "N/R")

                    if row['fecha_registro']:
                        st.caption(f"📅 Fecha de registro en sistema: {row['fecha_registro'][:16]}")
                    if row['observaciones']:
                        st.info(f"📝 Observaciones: {row['observaciones']}")

                    st.divider()
                    st.subheader("📎 Documentos de Salida")

                    emp_id = int(row['id'])
                    cedula = row['cedula']

                    # Documentos requeridos de salida
                    docs_salida = [
                        ("acta_finiquito", "1. Acta de Finiquito Firmada"),
                        ("aviso_salida", "2. Aviso de Salida Firmado"),
                        ("cheque_pago", "3. Cheque / Comprobante de Pago Firmado"),
                    ]

                    conn = get_db_connection()
                    sep_docs = pd.read_sql_query(
                        "SELECT * FROM separation_documents WHERE employee_id = ?",
                        conn, params=(emp_id,)
                    )
                    conn.close()

                    for tipo_key, tipo_label in docs_salida:
                        doc_ex = sep_docs[sep_docs['tipo_doc'] == tipo_key]
                        col1, col2, col3 = st.columns([2.5, 2, 1.5])
                        with col1:
                            st.markdown(f"**{tipo_label}**")
                        with col2:
                            if not doc_ex.empty:
                                fecha_c = doc_ex.iloc[0]['fecha_carga']
                                st.success(f"✅ Cargado — {fecha_c[:10] if fecha_c else ''}")
                            else:
                                st.warning("⏳ Pendiente")
                        with col3:
                            uploaded = st.file_uploader(
                                "Subir archivo",
                                key=f"sep_{emp_id}_{tipo_key}",
                                label_visibility="collapsed",
                                type=["pdf", "jpg", "jpeg", "png"]
                            )
                            if uploaded:
                                filename = f"{cedula}_{tipo_key}_{date.today()}.{uploaded.name.split('.')[-1]}"
                                ruta = save_uploaded_file(uploaded, f"salida_{cedula}", filename)
                                conn = get_db_connection()
                                conn.execute(
                                    "DELETE FROM separation_documents WHERE employee_id=? AND tipo_doc=?",
                                    (emp_id, tipo_key)
                                )
                                conn.execute(
                                    "INSERT INTO separation_documents (employee_id, tipo_doc, ruta_archivo, cargado_por) VALUES (?,?,?,?)",
                                    (emp_id, tipo_key, ruta, st.session_state['username'])
                                )
                                conn.commit()
                                conn.close()
                                st.success("✅ Documento guardado.")
                                safe_rerun()

                    # Progreso de documentos
                    total_docs = len(docs_salida)
                    cargados = sum(
                        1 for tk, _ in docs_salida
                        if not sep_docs[sep_docs['tipo_doc'] == tk].empty
                    )
                    st.progress(cargados / total_docs, text=f"Documentos cargados: {cargados}/{total_docs}")

    # ==========================================
    # MÓDULO: CONFIGURACIÓN GLOBAL
    # ==========================================
    elif menu == "Configuración Global":
        st.title("⚙️ Configuración del Sistema")
        t1, t2, t3 = st.tabs(["Parámetros", "Áreas", "Usuarios"])

        with t1:
            st.subheader("Salario Básico Unificado (SBU)")
            s = get_sbu()
            st.info(f"SBU actual: **${s:.2f}**")
            n_s = st.number_input("Nuevo valor del SBU", value=float(s), min_value=0.0)
            if st.button("💾 Actualizar SBU"):
                update_sbu(n_s)
                st.success(f"SBU actualizado a ${n_s:.2f}")
                safe_rerun()

        with t2:
            st.subheader("Áreas de la empresa")
            conn = get_db_connection()
            areas_all = pd.read_sql_query("SELECT * FROM areas", conn)
            conn.close()
            if not areas_all.empty:
                st.dataframe(areas_all[['id','nombre_area']], hide_index=True)
            n_ar = st.text_input("Nueva área")
            if st.button("➕ Añadir Área"):
                if n_ar:
                    conn = get_db_connection()
                    try:
                        conn.execute("INSERT INTO areas (nombre_area) VALUES (?)", (n_ar,))
                        conn.commit()
                        st.success(f"Área '{n_ar}' creada.")
                    except sqlite3.IntegrityError:
                        st.error("Esa área ya existe.")
                    finally:
                        conn.close()
                    safe_rerun()

        with t3:
            st.subheader("Gestión de usuarios")
            conn = get_db_connection()
            all_emps = pd.read_sql_query("SELECT id, nombre_completo FROM employees WHERE estado='Activo'", conn)
            conn.close()

            with st.form("u_form"):
                un = st.text_input("Nombre de usuario")
                pw = st.text_input("Contraseña", type="password")
                rl = st.selectbox("Rol", ["admin", "jefe"])
                eid_options = [f"{r['nombre_completo']} (ID:{r['id']})" for _, r in all_emps.iterrows()] if not all_emps.empty else ["Ninguno"]
                eid = st.selectbox("Empleado asociado", eid_options)

                if st.form_submit_button("Crear Usuario"):
                    if un and pw and eid != "Ninguno":
                        id_v = int(eid.split("ID:")[1].replace(")", ""))
                        conn = get_db_connection()
                        try:
                            conn.execute(
                                "INSERT INTO users (username, password, role, employee_id) VALUES (?,?,?,?)",
                                (un, pw, rl, id_v)
                            )
                            conn.commit()
                            st.success(f"Usuario '{un}' creado.")
                        except sqlite3.IntegrityError:
                            st.error("Nombre de usuario ya existe.")
                        finally:
                            conn.close()
                        safe_rerun()
                    else:
                        st.error("Completa todos los campos.")


if __name__ == "__main__":
    main()