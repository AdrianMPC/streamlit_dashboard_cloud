import os
import io
import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dotenv import load_dotenv
import altair as alt

# ============ CONFIG ============ #
st.set_page_config(page_title="Sistema de Asistencia UEP", layout="wide")
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Importar supabase solo si hay credenciales (para evitar error en entornos demo)
SUPABASE_AVAILABLE = False
try:
    if SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        SUPABASE_AVAILABLE = True
except Exception:
    SUPABASE_AVAILABLE = False

# ============ LOGIN BÁSICO ============ #
USERS = {
    "admin": "admin",
    "organizador": "organizador",
}

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None

# ============ DATA ACCESS LAYER ============ #
# Tablas esperadas en Supabase:
# - usuarios(id uuid, nombre text, correo text, rol text, facultad text, activo bool, creado_en timestamptz)
# - eventos(id uuid, titulo text, tipo text, facultad text, fecha date, hora_inicio time, hora_fin time, organizador_id uuid, ubicacion text, cupos int, created_at timestamptz)
# - asistencias(id bigint, evento_id uuid, usuario_id uuid, hora_checkin timestamptz, metodo text, valido bool, created_at timestamptz, origen text)

@st.cache_data(show_spinner=False, ttl=60)
def fetch_from_supabase():
    """Lee usuarios, eventos y asistencias desde Supabase y retorna dataframes."""
    if not SUPABASE_AVAILABLE:
        return None, None, None

    try:
        res_users = supabase.table("usuarios").select("*").execute()
        res_events = supabase.table("eventos").select("*").execute()
        res_att = supabase.table("asistencias").select("*").execute()

        df_users = pd.DataFrame(res_users.data) if res_users.data else pd.DataFrame()
        df_events = pd.DataFrame(res_events.data) if res_events.data else pd.DataFrame()
        df_att = pd.DataFrame(res_att.data) if res_att.data else pd.DataFrame()

        # Normalizaciones básicas
        if not df_att.empty and "hora_checkin" in df_att.columns:
            df_att["hora_checkin"] = pd.to_datetime(df_att["hora_checkin"])
        if not df_events.empty and "fecha" in df_events.columns:
            df_events["fecha"] = pd.to_datetime(df_events["fecha"]).dt.date

        return df_users, df_events, df_att
    except Exception as e:
        st.warning(f"No se pudo leer de Supabase: {e}")
        return None, None, None

@st.cache_data(show_spinner=False)
def generate_demo_data(seed=42):
    """Genera datos simulados con el mismo esquema para ver el dashboard sin Supabase."""
    np.random.seed(seed)

    # Usuarios
    facultades = ["Ingeniería", "Derecho", "Negocios", "Arquitectura"]
    roles = ["estudiante"]*120 + ["organizador"]*6 + ["admin"]*2
    usuarios = []
    for i in range(128):
        rol = roles[i]
        fac = np.random.choice(facultades) if rol in ["estudiante", "organizador"] else None
        usuarios.append({
            "id": f"u-{i:03}",
            "nombre": f"Usuario {i:03}",
            "correo": f"user{i:03}@uep.edu",
            "rol": rol,
            "facultad": fac,
            "activo": True,
            "creado_en": datetime.now() - timedelta(days=np.random.randint(1, 200))
        })
    df_users = pd.DataFrame(usuarios)

    # Eventos (últimos 30 días)
    tipos = ["charla", "taller", "seminario"]
    eventos = []
    base_date = datetime.now().date() - timedelta(days=30)
    for i in range(18):
        f = np.random.choice(facultades)
        d = base_date + timedelta(days=np.random.randint(0, 30))
        start = datetime.combine(d, datetime.min.time()) + timedelta(hours=int(np.random.choice([9, 11, 15, 18])))
        end = start + timedelta(hours=2)
        eventos.append({
            "id": f"e-{i:03}",
            "titulo": f"Evento {i:02} - {f}",
            "tipo": np.random.choice(tipos),
            "facultad": f,
            "fecha": d,
            "hora_inicio": start.time(),
            "hora_fin": end.time(),
            "organizador_id": np.random.choice(df_users.loc[df_users["rol"]=="organizador","id"]),
            "ubicacion": np.random.choice(["Auditorio A", "Auditorio B", "Sala 301", "Aula Magna"]),
            "cupos": np.random.randint(40, 120),
            "created_at": start - timedelta(days=3)
        })
    df_events = pd.DataFrame(eventos)

    # Asistencias
    asistencias = []
    for _, ev in df_events.iterrows():
        # universo de estudiantes
        candidates = df_users[df_users["rol"]=="estudiante"].sample(np.random.randint(30, 90))
        start_dt = datetime.combine(ev["fecha"], ev["hora_inicio"])
        for _, stu in candidates.iterrows():
            # probabilidad de asistencia por facultad (ligera variación)
            p = 0.75 if stu["facultad"] == ev["facultad"] else 0.6
            if np.random.rand() < p:
                offset_min = np.random.normal(loc=5, scale=12)  # minutos desde inicio
                check_in = start_dt + timedelta(minutes=max(-10, int(offset_min)))
                asistencias.append({
                    "id": len(asistencias)+1,
                    "evento_id": ev["id"],
                    "usuario_id": stu["id"],
                    "hora_checkin": check_in,
                    "metodo": np.random.choice(["QR","manual","NFC"], p=[0.8,0.15,0.05]),
                    "valido": True,
                    "created_at": check_in,
                    "origen": "demo"
                })
    df_att = pd.DataFrame(asistencias)

    return df_users, df_events, df_att

def get_data():
    """Obtén datos desde Supabase o datos demo si no hay conexión."""
    df_users, df_events, df_att = fetch_from_supabase()
    if df_users is None or df_events is None or df_att is None or df_users.empty or df_events.empty or df_att.empty:
        st.info("Usando datos de demostración (no se detectó conexión/tabla en Supabase).")
        return generate_demo_data()
    return df_users, df_events, df_att

# ============ UTILIDADES ============ #
def login_page():
    st.title("🎓 Sistema de Registro de Asistencia - UEP")
    st.subheader("Inicio de sesión")

    user = st.text_input("Usuario")
    password = st.text_input("Contraseña", type="password")

    if st.button("Iniciar sesión"):
        if user in USERS and USERS[user] == password:
            st.session_state.logged_in = True
            st.session_state.role = user
            st.success("Inicio de sesión exitoso")
            st.rerun()
        else:
            st.error("Credenciales incorrectas. Intente nuevamente.")

def kpis_header(df_events, df_att):
    # Eventos en periodo
    n_eventos = df_events["id"].nunique() if not df_events.empty else 0
    # Asistentes únicos
    asistentes_unicos = df_att["usuario_id"].nunique() if not df_att.empty else 0
    # Cumplimiento: presentes / cupos estimados (aprox)
    # Para demo: usar promedio de cupos por evento
    if not df_events.empty and not df_att.empty:
        total_cupos = df_events["cupos"].sum()
        presentes = df_att.groupby("evento_id")["usuario_id"].nunique().sum()
        cumplimiento = 100 * (presentes / total_cupos) if total_cupos > 0 else 0
    else:
        cumplimiento = 0.0
    # No-show: asumiendo confirmaciones ≈ 0.8 * cupos en demo (ajusta con tu tabla de invitaciones/confirmados)
    no_show = max(0.0, 100 - cumplimiento * 0.8) if cumplimiento > 0 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Eventos", n_eventos)
    c2.metric("Asistentes únicos", asistentes_unicos)
    c3.metric("% Cumplimiento", f"{cumplimiento:.1f}%")
    c4.metric("No-show (aprox.)", f"{no_show:.1f}%")

# ============ VISTAS ============ #
def vista_academica():
    st.title("📊 Vista Académica - Decanatos / Coordinación")
    st.caption("Análisis por facultad, tipo de evento y periodo")

    df_users, df_events, df_att = get_data()

    # Filtros
    colf1, colf2, colf3 = st.columns(3)
    facultades = sorted([f for f in df_events["facultad"].dropna().unique()]) if not df_events.empty else []
    tipos = sorted([t for t in df_events["tipo"].dropna().unique()]) if not df_events.empty else []
    min_date = df_events["fecha"].min() if not df_events.empty else datetime.now().date()
    max_date = df_events["fecha"].max() if not df_events.empty else datetime.now().date()

    fac_sel = colf1.multiselect("Facultad", facultades, default=facultades)
    tipo_sel = colf2.multiselect("Tipo de evento", tipos, default=tipos)
    date_range = colf3.date_input("Rango de fechas", value=(min_date, max_date))

    # Aplicar filtros
    if not df_events.empty:
        mask_e = (df_events["facultad"].isin(fac_sel)) & (df_events["tipo"].isin(tipo_sel))
        if isinstance(date_range, tuple) and len(date_range) == 2:
            d1, d2 = date_range
            mask_e &= (df_events["fecha"] >= d1) & (df_events["fecha"] <= d2)
        df_events_f = df_events[mask_e].copy()
        df_att_f = df_att[df_att["evento_id"].isin(df_events_f["id"])].copy()
    else:
        df_events_f, df_att_f = df_events.copy(), df_att.copy()

    # KPIs
    kpis_header(df_events_f, df_att_f)

    # -------- Gráfico 1: Serie temporal global -------- #
    st.subheader("Tendencia diaria de asistencia")
    if not df_att_f.empty:
        df_tmp = df_att_f.copy()
        df_tmp["fecha"] = df_tmp["hora_checkin"].dt.date
        trend = df_tmp.groupby("fecha")["usuario_id"].nunique().reset_index(name="asistentes")
        st.line_chart(trend.set_index("fecha"))
    else:
        st.info("Sin datos para la tendencia.")

    # -------- Gráfico 2: Barras apiladas por facultad (Presentes / Tarde / No-show) -------- #
    st.subheader("Comparativo por facultad")
    if not df_att_f.empty and not df_events_f.empty:
        # 1) traer inicio del evento y facultad/cupos al DF de asistencias filtradas
        ev_cols = ["id", "fecha", "hora_inicio", "facultad", "cupos"]
        ev_meta = df_events_f[ev_cols].copy()
        ev_meta["inicio_dt"] = ev_meta.apply(lambda r: datetime.combine(r["fecha"], r["hora_inicio"]), axis=1)

        # unir asistencias con metadatos del evento (para tener inicio_dt y facultad)
        m = df_att_f.merge(ev_meta[["id", "inicio_dt", "facultad", "cupos"]],
                        left_on="evento_id", right_on="id", how="left", suffixes=("", "_e"))

        # 2) calcular latencia y estado
        m["lat_min"] = (m["hora_checkin"] - m["inicio_dt"]).dt.total_seconds() / 60
        m["estado"] = np.where(m["lat_min"] <= 15, "Presente", "Tarde")

        # 3) presentes por evento para estimar no-show (si no tienes confirmaciones reales)
        pres_por_evento = m.groupby("evento_id")["usuario_id"].nunique()

        ev_fac = ev_meta.set_index("id")[["facultad", "cupos"]].copy()
        ev_fac["presentes"] = pres_por_evento
        ev_fac["presentes"] = ev_fac["presentes"].fillna(0)

        # proxy: asumimos confirmaciones ≈ 0.8 * cupos; ajusta si tienes tabla real de confirmaciones
        ev_fac["no_show"] = (ev_fac["cupos"] * 0.8 - ev_fac["presentes"]).clip(lower=0)

        # 4) conteos por estado y facultad
        # ojo: m ya tiene 'facultad' por la unión con ev_meta
        by_fac_estado = m.groupby(["facultad", "estado"])["usuario_id"].nunique().unstack(fill_value=0)

        # añadir la columna No-show agregada por facultad
        no_show_fac = ev_fac.groupby("facultad")["no_show"].sum()
        by_fac_estado["No-show"] = no_show_fac.reindex(by_fac_estado.index).fillna(0)

        st.bar_chart(by_fac_estado)
    else:
        st.info("Sin datos para el comparativo por facultad.")

    # -------- Gráfico 3: Heatmap día-hora -------- #
    st.subheader("Mapa de calor por hora y facultad")
    if not df_att_f.empty:
        tmp = df_att_f.copy()
        tmp["hora"] = tmp["hora_checkin"].dt.hour
        tmp = tmp.merge(df_events_f[["id","facultad"]], left_on="evento_id", right_on="id", how="left")
        heat = tmp.pivot_table(index="facultad", columns="hora", values="usuario_id", aggfunc="nunique").fillna(0)
        st.dataframe(heat.style.background_gradient(axis=None))
    else:
        st.info("Sin datos para el heatmap.")

    # Tabla descargable
    st.subheader("Detalle de eventos filtrados")
    st.dataframe(df_events_f)
    csv_bytes = df_events_f.to_csv(index=False).encode("utf-8")
    st.download_button("Descargar eventos CSV", data=csv_bytes, file_name="eventos_filtrados.csv", mime="text/csv")


def vista_organizador():
    st.title("📋 Vista del Organizador - Gestión de Eventos")
    st.caption("Monitoreo de check-ins, tardanzas y asistencia por evento")

    df_users, df_events, df_att = get_data()

    # Selección de evento
    if df_events.empty:
        st.info("No hay eventos disponibles.")
        return
    evento_sel = st.selectbox("Selecciona tu evento", df_events["titulo"] + " | " + df_events["id"])
    ev_id = evento_sel.split("|")[-1].strip()

    df_ev = df_events[df_events["id"] == ev_id]
    df_ev_att = df_att[df_att["evento_id"] == ev_id].copy()

    if df_ev.empty:
        st.warning("Evento no encontrado.")
        return

    # KPIs de evento
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Asistentes", df_ev_att["usuario_id"].nunique())
    col2.metric("Cupos", int(df_ev["cupos"].values[0]) if "cupos" in df_ev.columns else 0)

    if not df_ev_att.empty:
        start_dt = datetime.combine(df_ev["fecha"].values[0], df_ev["hora_inicio"].values[0])
        df_ev_att["lat_min"] = (df_ev_att["hora_checkin"] - start_dt).dt.total_seconds()/60
        tardanza_media = df_ev_att["lat_min"].clip(lower=0).mean()
        col3.metric("Tardanza media (min)", f"{tardanza_media:.1f}")
        tasa_exito = (df_ev_att["metodo"] == "QR").mean()*100
        col4.metric("Tasa de escaneo QR", f"{tasa_exito:.1f}%")

        # Check-ins por minuto
        st.subheader("Flujo de check-ins por minuto")
        df_ev_att["minuto"] = df_ev_att["hora_checkin"].dt.floor("min")
        dens = df_ev_att.groupby("minuto")["usuario_id"].nunique().reset_index(name="checkins")
        st.area_chart(dens.set_index("minuto"))

       # Histograma de latencia
        st.subheader("Distribución de latencia de ingreso")

        bins = [-10, 0, 5, 10, 15, 20, 30, 60]
        cats = pd.cut(df_ev_att["lat_min"], bins=bins, include_lowest=True)
        hist = cats.value_counts().sort_index()

        # Altair no acepta Interval como eje; conviértelo a string o a punto medio
        df_hist = hist.rename_axis("bin").reset_index(name="count")
        df_hist["bin"] = df_hist["bin"].astype(str)

        chart = (
            alt.Chart(df_hist)
            .mark_bar()
            .encode(
                x=alt.X("bin:N", title="Minutos desde inicio"),
                y=alt.Y("count:Q", title="Asistentes"),
                tooltip=["bin", "count"]
            )
            .properties(height=300)
        )
        st.altair_chart(chart, width="stretch")


        # Detalle por alumno
        st.subheader("Detalle por alumno")
        detalle = df_ev_att.merge(
            df_users[["id","nombre","facultad"]],
            left_on="usuario_id",
            right_on="id",
            how="left"
        )[["usuario_id","nombre","facultad","hora_checkin","metodo","lat_min"]].sort_values("hora_checkin")
        st.dataframe(detalle)

        csv_det = detalle.to_csv(index=False).encode("utf-8")
        st.download_button("Descargar detalle CSV", data=csv_det, file_name=f"detalle_{ev_id}.csv", mime="text/csv")
    else:
        st.info("Este evento aún no tiene asistencias registradas.")

# ============ ENRUTAMIENTO ============ #
def main():
    if not st.session_state.logged_in:
        login_page()
        return

    # Sidebar común
    st.sidebar.title("Menú")
    if st.sidebar.button("Cerrar sesión"):
        st.session_state.logged_in = False
        st.session_state.role = None
        st.rerun()

    # Rutas por rol
    if st.session_state.role == "admin":
        vista_academica()
    elif st.session_state.role == "organizador":
        vista_organizador()
    else:
        st.error("Rol no reconocido.")
        if st.button("Cerrar sesión"):
            st.session_state.logged_in = False
            st.session_state.role = None
            st.experimental_rerun()

if __name__ == "__main__":
    main()
