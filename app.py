from dotenv import load_dotenv
load_dotenv(override=True)

import os
import numpy as np
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import csv
import json
import urllib.request
import urllib.error
import pandas as pd

import psycopg
from psycopg.rows import dict_row
from psycopg import errors
from decimal import Decimal

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-cambiar-en-produccion')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB por archivo

NIVELES_FERTILIDAD = {
    "N Total": {
        "escala": ["Muy bajo", "Bajo", "Medio", "Alto", "Muy alto"],
        "umbrales": [(1000, "Muy alto"), (800, "Alto"), (600, "Medio"), (400, "Bajo")],
        "minimo": "Muy bajo",
    },
    "Fósforo (P)": {
        "escala": ["Muy bajo", "Bajo", "Medio", "Alto", "Muy alto"],
        "umbrales": [(10, "Muy alto"), (4.5, "Alto"), (3.5, "Medio"), (2.5, "Bajo")],
        "minimo": "Muy bajo",
    },
    "Potasio (K) intercambiable": {
        "escala": ["Muy pobre", "Pobre", "Bueno", "Alto"],
        "umbrales": [(200, "Alto"), (150, "Bueno"), (50, "Pobre")],
        "minimo": "Muy pobre",
    },
}

def clasificar_nivel(parametro, valor):
    cfg = NIVELES_FERTILIDAD.get(parametro)
    if not cfg or valor in (None, ""):
        return ""
    try:
        v = float(str(valor).replace(',', '.').strip())
    except (ValueError, TypeError):
        return ""
    for umbral, etiqueta in cfg["umbrales"]:
        if v >= umbral:
            return etiqueta
    return cfg["minimo"]

def obtener_conexion():
    url_bd = os.environ.get('DATABASE_URL')
    conexion = psycopg.connect(url_bd, row_factory=dict_row)
    return conexion

def crear_tablas():
    conexion = obtener_conexion()
    if conexion:
        try:
            cur = conexion.cursor()
            cur.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                            id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS muestras (
                            id SERIAL PRIMARY KEY, usuario_id INTEGER NOT NULL, nombre_muestra TEXT NOT NULL, 
                            cultivo TEXT, textura TEXT, latitud NUMERIC, longitud NUMERIC, 
                            descripcion TEXT, informacion_relevante TEXT, 
                            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                            UNIQUE(usuario_id, nombre_muestra))''')
            cur.execute('''CREATE TABLE IF NOT EXISTS carbono_activo (
                            id SERIAL PRIMARY KEY, muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE, 
                            resultado_carbono NUMERIC, peso_suelo NUMERIC, abs_muestra NUMERIC, 
                            abs_1 NUMERIC, abs_2 NUMERIC, abs_3 NUMERIC, abs_4 NUMERIC)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS ph_conductividad (
                            id SERIAL PRIMARY KEY, muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE, 
                            ph NUMERIC, conductividad NUMERIC)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS materia_organica (
                            id SERIAL PRIMARY KEY, muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE, 
                            resultado_porcentaje NUMERIC, peso_particulas NUMERIC, peso_suelo NUMERIC, 
                            peso_filtro NUMERIC, peso_muestra_con_filtro NUMERIC)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS estabilidad_agregados (
                            id SERIAL PRIMARY KEY, muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE, 
                            porcentaje_mayor_2mm NUMERIC, porcentaje_250_2mm NUMERIC, peso_inicial NUMERIC, 
                            peso_filtro NUMERIC, peso_piedras NUMERIC, peso_fraccion_mayor NUMERIC, 
                            peso_fraccion_250 NUMERIC, peso_recipiente_piedras NUMERIC, peso_piedras_con_recipiente NUMERIC)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS fosforo_olsen (
                            id SERIAL PRIMARY KEY, muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE,
                            resultado_ppm NUMERIC, resultado_mg_kg NUMERIC, peso_suelo NUMERIC,
                            vol_extracto NUMERIC, vol_dilucion NUMERIC, abs_muestra NUMERIC,
                            abs_0 NUMERIC, abs_01 NUMERIC, abs_02 NUMERIC, abs_04 NUMERIC, abs_06 NUMERIC, abs_08 NUMERIC)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS respiracion_suelo (
                            id SERIAL PRIMARY KEY, muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE,
                            peso_suelo NUMERIC, co2_initial NUMERIC, co2_final NUMERIC, horas NUMERIC, ugc_gsoil NUMERIC,
                            curva_tiempo TEXT, curva_co2 TEXT)''')
            conexion.commit()

            try:
                cur.execute('''CREATE TABLE IF NOT EXISTS analisis_externo (
                    id SERIAL PRIMARY KEY,
                    muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE,
                    laboratorio TEXT,
                    nro_protocolo TEXT,
                    fecha_recepcion DATE,
                    fecha_informe DATE,
                    archivo_url TEXT,
                    observaciones TEXT,
                    determinaciones TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                conexion.commit()
            except Exception:
                conexion.rollback()

            try:
                cur.execute("ALTER TABLE muestras ADD COLUMN foto_macrofauna TEXT;")
            except Exception:
                conexion.rollback()
            try:
                cur.execute("ALTER TABLE muestras ADD COLUMN foto_cromatografia TEXT;")
            except Exception:
                conexion.rollback()
            try:
                cur.execute("ALTER TABLE muestras ADD COLUMN obs_cromatografia TEXT;")
            except Exception:
                conexion.rollback()
                
            # NUEVO CAMPO PARA SLAKES
            try:
                cur.execute("ALTER TABLE estabilidad_agregados ADD COLUMN indice_slakes NUMERIC;")
            except Exception:
                conexion.rollback()

            # CAMPO VOLUMEN DE SEDIMENTACION
            try:
                cur.execute("ALTER TABLE muestras ADD COLUMN IF NOT EXISTS volumen_sedimentacion TEXT;")
                conexion.commit()
            except Exception:
                conexion.rollback()

            # LECTURAS BRUTAS DEL ENSAYO DE VOLUMEN DE SEDIMENTACION
            try:
                cur.execute("ALTER TABLE muestras ADD COLUMN IF NOT EXISTS vs_lectura DOUBLE PRECISION;")
                cur.execute("ALTER TABLE muestras ADD COLUMN IF NOT EXISTS vs_peso    DOUBLE PRECISION;")
                conexion.commit()
            except Exception:
                conexion.rollback()

            # PDF DEL INFORME EXTERNO
            try:
                cur.execute("ALTER TABLE analisis_externo ADD COLUMN IF NOT EXISTS archivo_pdf BYTEA;")
                cur.execute("ALTER TABLE analisis_externo ADD COLUMN IF NOT EXISTS archivo_nombre TEXT;")
                conexion.commit()
            except Exception:
                conexion.rollback()

            # MIGRACION CURVA CALIBRACION FOSFORO: renombrar columnas al nuevo esquema de 6 puntos
            try:
                cur.execute("""
                    DO $$ BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fosforo_olsen' AND column_name='abs_05') THEN
                            ALTER TABLE fosforo_olsen RENAME COLUMN abs_05 TO abs_01;
                            ALTER TABLE fosforo_olsen RENAME COLUMN abs_15 TO abs_04;
                        END IF;
                    END $$;
                """)
                conexion.commit()
            except Exception:
                conexion.rollback()
            try:
                cur.execute("""
                    DO $$ BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fosforo_olsen' AND column_name='abs_1') THEN
                            ALTER TABLE fosforo_olsen RENAME COLUMN abs_1 TO abs_02;
                        END IF;
                    END $$;
                """)
                conexion.commit()
            except Exception:
                conexion.rollback()
            try:
                cur.execute("""
                    DO $$ BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fosforo_olsen' AND column_name='abs_2') THEN
                            ALTER TABLE fosforo_olsen RENAME COLUMN abs_2 TO abs_06;
                        END IF;
                    END $$;
                """)
                conexion.commit()
            except Exception:
                conexion.rollback()
            try:
                cur.execute("ALTER TABLE fosforo_olsen ADD COLUMN IF NOT EXISTS abs_08 NUMERIC;")
                conexion.commit()
            except Exception:
                conexion.rollback()

            conexion.commit()

            # SurveyStack integration
            try:
                cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ss_token TEXT;")
                cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ss_token_expiry TIMESTAMP;")
                cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ss_user_id TEXT;")
                cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ss_email TEXT;")
                conexion.commit()
            except Exception:
                conexion.rollback()
            try:
                cur.execute('''CREATE TABLE IF NOT EXISTS usuario_surveys (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                    nombre TEXT NOT NULL,
                    survey_id TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    UNIQUE(usuario_id, survey_id)
                )''')
                conexion.commit()
            except Exception:
                conexion.rollback()
            try:
                for nombre, survey_id, tipo in [
                    ('Muestra Suelo - LAA', '6a08920d4c396d25617db9ed', 'muestra_suelo'),
                    ('Test Parcela - LAA', '69e27691ca4d1d7e5d39db88', 'test_parcela'),
                    ('Test Productor - LAA', '6a022adad40876f3b64849a7', 'test_productor'),
                ]:
                    cur.execute('''INSERT INTO usuario_surveys (usuario_id, nombre, survey_id, tipo)
                        SELECT id, %s, %s, %s FROM usuarios
                        ON CONFLICT (usuario_id, survey_id) DO NOTHING''', (nombre, survey_id, tipo))
                conexion.commit()
            except Exception:
                conexion.rollback()
            try:
                cur.execute('''CREATE TABLE IF NOT EXISTS fincas (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                    ss_submission_id TEXT,
                    nombre TEXT NOT NULL,
                    productor TEXT,
                    telefono TEXT,
                    localidad TEXT,
                    provincia TEXT,
                    hectareas NUMERIC,
                    tipo_produccion TEXT,
                    geojson TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(usuario_id, ss_submission_id)
                )''')
                conexion.commit()
            except Exception:
                conexion.rollback()
            try:
                cur.execute('''CREATE TABLE IF NOT EXISTS parcelas (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                    finca_nombre TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    nombre_completo TEXT,
                    certificacion TEXT,
                    cultivo TEXT,
                    geojson TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(usuario_id, finca_nombre, nombre)
                )''')
                conexion.commit()
            except Exception:
                conexion.rollback()

            cur.close()
        except Exception as e:
            print("Error al crear tablas:", e)
        finally:
            conexion.close()

crear_tablas()

@app.route('/registro', methods=['POST'])
def registro():
    username = request.form['new_username']
    password = request.form['new_password']
    hashed_password = generate_password_hash(password)
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('INSERT INTO usuarios (username, password) VALUES (%s, %s) RETURNING id', (username, hashed_password))
        new_user = cur.fetchone()
        if new_user:
            for nombre, survey_id, tipo in [
                ('Muestra Suelo - LAA', '6a08920d4c396d25617db9ed', 'muestra_suelo'),
                ('Test Parcela - LAA', '69e27691ca4d1d7e5d39db88', 'test_parcela'),
                ('Test Productor - LAA', '6a022adad40876f3b64849a7', 'test_productor'),
            ]:
                cur.execute('INSERT INTO usuario_surveys (usuario_id, nombre, survey_id, tipo) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING', (new_user['id'], nombre, survey_id, tipo))
        conexion.commit()
        flash('Cuenta creada. Por favor, inicia sesión.', 'success')
    except errors.UniqueViolation:
        conexion.rollback()
        flash('Ese usuario ya existe.', 'danger')
    finally:
        cur.close()
        conexion.close()
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conexion = obtener_conexion()
        cur = conexion.cursor()
        cur.execute('SELECT * FROM usuarios WHERE username = %s', (username,))
        user = cur.fetchone()
        cur.close()
        conexion.close()
        if user and check_password_hash(user['password'], password):
            session['usuario_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('inicio'))
        else:
            flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def inicio():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    usuario_id = session['usuario_id']
    username = session['username']
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        if request.method == 'POST':
            tipo_formulario = request.form.get('form_type')
            muestra_id_raw = request.form.get('muestra_id')
            muestra_id = None
            if muestra_id_raw:
                if str(muestra_id_raw).startswith('offline_'):
                    nombre_m = muestra_id_raw.replace('offline_', '')
                    cur.execute('SELECT id FROM muestras WHERE nombre_muestra = %s AND usuario_id = %s', (nombre_m, usuario_id))
                    res = cur.fetchone()
                    if res: muestra_id = res['id']
                else:
                    muestra_id = muestra_id_raw
            
            if tipo_formulario == 'registro_muestra':
                nombre, cultivo, descripcion, info = request.form['nombre'], request.form['cultivo'], request.form['descripcion'], request.form['info']
                # Se eliminó la textura del form de Muestras (se maneja en su pestaña)
                lat_str, lon_str = request.form.get('latitud'), request.form.get('longitud')
                latitud = float(lat_str) if lat_str else None
                longitud = float(lon_str) if lon_str else None
                muestra_id_editar = request.form.get('muestra_id_editar')
                if muestra_id_editar:
                    cur.execute('''UPDATE muestras SET nombre_muestra=%s, cultivo=%s, latitud=%s, longitud=%s, descripcion=%s, informacion_relevante=%s WHERE id=%s AND usuario_id=%s''', (nombre, cultivo, latitud, longitud, descripcion, info, muestra_id_editar, usuario_id))
                    flash('Muestra actualizada exitosamente.', 'info')
                else:
                    try:
                        cur.execute('''INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, descripcion, informacion_relevante, latitud, longitud) VALUES (%s, %s, %s, %s, %s, %s, %s)''', (usuario_id, nombre, cultivo, descripcion, info, latitud, longitud))
                        flash('Muestra creada exitosamente.', 'success')
                    except errors.UniqueViolation:
                        conexion.rollback()
                        cur.execute('''UPDATE muestras SET cultivo=%s, descripcion=%s, informacion_relevante=%s, latitud=%s, longitud=%s WHERE usuario_id=%s AND nombre_muestra=%s''', (cultivo, descripcion, info, latitud, longitud, usuario_id, nombre))
                        flash('Muestra actualizada exitosamente.', 'info')
                conexion.commit()
                return redirect(url_for('inicio') + '#muestras')

            if not muestra_id and tipo_formulario != 'registro_muestra':
                 return redirect(url_for('inicio'))

            if tipo_formulario == 'textura_suelo':
                cur.execute('UPDATE muestras SET textura = %s WHERE id = %s AND usuario_id = %s', (request.form['textura'], muestra_id, usuario_id))
                conexion.commit()
                flash('Textura guardada exitosamente.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#textura')

            if tipo_formulario == 'volumen_sedimentacion_suelo':
                def _num(field):
                    v = (request.form.get(field) or '').strip().replace(',', '.')
                    return float(v) if v else None
                cur.execute(
                    'UPDATE muestras SET volumen_sedimentacion = %s, vs_lectura = %s, vs_peso = %s WHERE id = %s AND usuario_id = %s',
                    (request.form['volumen_sedimentacion'], _num('vs_lectura'), _num('vs_peso'), muestra_id, usuario_id)
                )
                conexion.commit()
                flash('Volumen de sedimentación guardado exitosamente.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#vol-sedimentacion')

            elif tipo_formulario == 'respiracion_suelo':
                peso_g = float(request.form.get('peso_suelo', 30.0))
                archivo = request.files.get('archivo_csv')
                if archivo and archivo.filename.endswith('.csv'):
                    try:
                        header = archivo.readline().decode('utf-8')
                        archivo.seek(0)
                        sep = ';' if ';' in header else ','
                        df = pd.read_csv(archivo, sep=sep)
                        df.columns = df.columns.str.strip().str.lower()
                        if 'timestamp' in df.columns and 'co2' in df.columns:
                            df['timestamp'] = pd.to_datetime(df['timestamp'], format='%d-%b-%y %H:%M:%S', errors='coerce')
                            df = df.dropna(subset=['timestamp', 'co2']).sort_values('timestamp')
                            if not df.empty:
                                df['minutes'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds() / 60.0
                                jar_vol, soil_vol, temp, Rconst, conversionFactor2 = 472, 32, 298, 82.05, 12000
                                headspace = jar_vol - soil_vol
                                co2_initial = float(df['co2'].iloc[:2].mean())
                                t0 = df['minutes'].iloc[0]
                                idx_final = (df['minutes'] - (t0 + 1440)).abs().idxmin()
                                t_final = float(df['minutes'].loc[idx_final])
                                co2_final = float(df['co2'].loc[idx_final])
                                hours = (t_final - t0) / 60.0
                                if hours <= 0: hours = 1.0 
                                co2_increase = (co2_final - co2_initial) * (24.0 / hours)
                                ugc_gsoil = ((co2_increase * headspace) / (peso_g * 1000.0) / (temp * Rconst)) * conversionFactor2
                                step = max(1, len(df) // 100)
                                df_plot = df.iloc[::step]
                                curva_tiempo = json.dumps(df_plot['minutes'].round(1).tolist())
                                curva_co2 = json.dumps(df_plot['co2'].round(1).tolist())
                                cur.execute('DELETE FROM respiracion_suelo WHERE muestra_id = %s', (muestra_id,))
                                cur.execute('''INSERT INTO respiracion_suelo (muestra_id, peso_suelo, co2_initial, co2_final, horas, ugc_gsoil, curva_tiempo, curva_co2) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', (muestra_id, peso_g, co2_initial, co2_final, hours, ugc_gsoil, curva_tiempo, curva_co2))
                                conexion.commit()
                                flash('Curva de respiración procesada y graficada con éxito.', 'success')
                            else: flash('El CSV no tiene datos temporales válidos.', 'danger')
                        else: flash('El archivo no tiene las columnas "timestamp" y "co2".', 'danger')
                    except Exception as e: flash(f'Error al procesar el CSV: {str(e)}', 'danger')
                else: flash('Por favor sube un archivo .csv válido.', 'warning')
                return redirect(url_for('inicio', m=muestra_id) + '#respiracion')

            elif tipo_formulario == 'carbono_activo':
                peso_kg = float(request.form.get('peso_suelo_carbono', 2.5)) / 1000
                a1, a2, a3, a4, abs_m = float(request.form['abs_1']), float(request.form['abs_2']), float(request.form['abs_3']), float(request.form['abs_4']), float(request.form['abs_muestra'])
                conc = np.array([0.005, 0.01, 0.015, 0.02])
                absor = np.array([a1, a2, a3, a4])
                resultado = stats.linregress(absor, conc)
                poxc = (0.02 - (resultado.intercept + (resultado.slope * abs_m))) * 9000 * (0.02 / peso_kg)
                cur.execute('DELETE FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO carbono_activo (muestra_id, resultado_carbono, peso_suelo, abs_muestra, abs_1, abs_2, abs_3, abs_4) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', (muestra_id, poxc, peso_kg*1000, abs_m, a1, a2, a3, a4))
                conexion.commit()
                flash('POXC Calculado exitosamente.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#carbono')

            elif tipo_formulario == 'fosforo_olsen':
                peso_g, vol_ext, vol_dil = float(request.form.get('peso_suelo', 2.5)), float(request.form.get('vol_extracto', 7.0)), float(request.form.get('vol_dilucion', 20.0))
                abs_m, a0, a01, a02, a04, a06, a08 = float(request.form['abs_muestra']), float(request.form['abs_0']), float(request.form['abs_01']), float(request.form['abs_02']), float(request.form['abs_04']), float(request.form['abs_06']), float(request.form['abs_08'])
                conc = np.array([0.0, 0.1, 0.2, 0.4, 0.6, 0.8])
                absor = np.array([a0, a01, a02, a04, a06, a08])
                resultado = stats.linregress(conc, absor)
                ppm = (abs_m - resultado.intercept) / resultado.slope if resultado.slope != 0 else 0
                p_disponible = ppm * (vol_dil / vol_ext) * 0.025 / (peso_g / 1000)
                cur.execute('DELETE FROM fosforo_olsen WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO fosforo_olsen (muestra_id, resultado_ppm, resultado_mg_kg, peso_suelo, vol_extracto, vol_dilucion, abs_muestra, abs_0, abs_01, abs_02, abs_04, abs_06, abs_08) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', (muestra_id, ppm, p_disponible, peso_g, vol_ext, vol_dil, abs_m, a0, a01, a02, a04, a06, a08))
                conexion.commit()
                flash('Fósforo calculado exitosamente.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#fosforo')

            elif tipo_formulario == 'ph_conductividad':
                ph_str = request.form.get('ph')
                cond_str = request.form.get('conductividad')
                ph_num = float(ph_str) if ph_str and ph_str.strip() != '' else None
                cond_num = float(cond_str) if cond_str and cond_str.strip() != '' else None
                
                cur.execute('DELETE FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
                cur.execute('INSERT INTO ph_conductividad (muestra_id, ph, conductividad) VALUES (%s, %s, %s)', (muestra_id, ph_num, cond_num))
                conexion.commit()
                flash('Valores de pH y/o Conductividad guardados.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#ph')

            elif tipo_formulario == 'materia_organica':
                pf_mop, pm_filtro, ps = float(request.form['peso_filtro_mop']), float(request.form['peso_muestra_con_filtro']), float(request.form['peso_suelo'])
                pp_neto = pm_filtro - pf_mop
                mop_porcentaje = (pp_neto / ps) * 100
                cur.execute('DELETE FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO materia_organica (muestra_id, resultado_porcentaje, peso_particulas, peso_suelo, peso_filtro, peso_muestra_con_filtro) VALUES (%s, %s, %s, %s, %s, %s)''', (muestra_id, mop_porcentaje, pp_neto, ps, pf_mop, pm_filtro))
                conexion.commit()
                flash('MOP calculado.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#mop')

            elif tipo_formulario == 'estabilidad_agregados':
                slakes_str = request.form.get('indice_slakes')
                slakes_num = float(slakes_str) if slakes_str and slakes_str.strip() != '' else None
                
                cur.execute('DELETE FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO estabilidad_agregados (muestra_id, indice_slakes) VALUES (%s, %s)''', (muestra_id, slakes_num))
                conexion.commit()
                flash('Índice Slakes guardado exitosamente.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#estab')

            elif tipo_formulario == 'macrofauna':
                url_foto_manual = request.form.get('foto_macrofauna')
                if not url_foto_manual:
                    flash('Debes esperar a que la foto suba.', 'danger')
                    return redirect(url_for('inicio', m=muestra_id) + '#macrofauna')
                cur.execute('''UPDATE muestras SET foto_macrofauna = %s WHERE id = %s AND usuario_id = %s''', (url_foto_manual, muestra_id, usuario_id))
                conexion.commit()
                flash('Foto guardada.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#macrofauna')

            elif tipo_formulario == 'cromatografia':
                url_foto_cromo = request.form.get('foto_cromatografia')
                obs_cromo = request.form.get('obs_cromatografia')
                if not url_foto_cromo and not obs_cromo:
                    flash('Debes adjuntar al menos una foto u observación.', 'danger')
                    return redirect(url_for('inicio', m=muestra_id) + '#cromatografia')
                cur.execute('''UPDATE muestras SET foto_cromatografia = %s, obs_cromatografia = %s WHERE id = %s AND usuario_id = %s''', (url_foto_cromo, obs_cromo, muestra_id, usuario_id))
                conexion.commit()
                flash('Registro de Cromatografía guardado.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#cromatografia')

            elif tipo_formulario == 'analisis_externo':
                laboratorio    = request.form.get('laboratorio')
                nro_protocolo  = request.form.get('nro_protocolo')
                fecha_recepcion = request.form.get('fecha_recepcion') or None
                fecha_informe  = request.form.get('fecha_informe') or None
                observaciones  = request.form.get('observaciones')
                try:
                    deters = json.loads(request.form.get('determinaciones') or '[]')
                except Exception:
                    deters = []

                for d in deters:
                    d['nivel'] = clasificar_nivel(d.get('parametro'), d.get('valor'))

                archivo = request.files.get('archivo_pdf')
                pdf_bytes = None
                pdf_nombre = None
                if archivo and archivo.filename:
                    if not archivo.filename.lower().endswith('.pdf'):
                        flash('El archivo del informe debe ser un PDF.', 'danger')
                        return redirect(url_for('inicio', m=muestra_id) + '#analisis-externo')
                    pdf_bytes = archivo.read()
                    pdf_nombre = archivo.filename

                if pdf_bytes is None:
                    cur.execute('SELECT archivo_pdf, archivo_nombre FROM analisis_externo WHERE muestra_id = %s', (muestra_id,))
                    prev = cur.fetchone()
                    if prev:
                        pdf_bytes  = prev['archivo_pdf']
                        pdf_nombre = prev['archivo_nombre']

                cur.execute('DELETE FROM analisis_externo WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO analisis_externo
                    (muestra_id, laboratorio, nro_protocolo, fecha_recepcion, fecha_informe,
                     observaciones, determinaciones, archivo_pdf, archivo_nombre)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (muestra_id, laboratorio, nro_protocolo, fecha_recepcion, fecha_informe,
                     observaciones, json.dumps(deters), pdf_bytes, pdf_nombre))
                conexion.commit()
                flash('Análisis externo guardado.', 'success')
                return redirect(url_for('inicio', m=muestra_id) + '#analisis-externo')

        cur.execute('SELECT id, nombre_muestra FROM muestras WHERE usuario_id = %s ORDER BY id DESC', (usuario_id,))
        muestras_db = cur.fetchall()
        consulta_consolidado = '''SELECT m.id, m.nombre_muestra, m.cultivo, m.textura, m.volumen_sedimentacion, m.descripcion, m.informacion_relevante, m.latitud, m.longitud, m.foto_macrofauna,
                                  m.foto_cromatografia, m.obs_cromatografia,
                                  c.resultado_carbono, p.ph, p.conductividad, mo.resultado_porcentaje AS mop,
                                  ea.indice_slakes, fo.resultado_mg_kg AS fosforo, fo.resultado_ppm AS fosforo_ppm,
                                  rs.ugc_gsoil AS respiracion, rs.co2_initial, rs.co2_final, rs.curva_tiempo, rs.curva_co2,
                                  ae.determinaciones AS det_externo, ae.laboratorio AS lab_externo,
                                  ae.nro_protocolo AS nro_protocolo_ext,
                                  (ae.archivo_pdf IS NOT NULL) AS tiene_pdf, ae.archivo_nombre
                                  FROM muestras m
                                  LEFT JOIN carbono_activo c ON m.id = c.muestra_id
                                  LEFT JOIN ph_conductividad p ON m.id = p.muestra_id
                                  LEFT JOIN materia_organica mo ON m.id = mo.muestra_id
                                  LEFT JOIN estabilidad_agregados ea ON m.id = ea.muestra_id
                                  LEFT JOIN fosforo_olsen fo ON m.id = fo.muestra_id
                                  LEFT JOIN respiracion_suelo rs ON m.id = rs.muestra_id
                                  LEFT JOIN analisis_externo ae ON m.id = ae.muestra_id
                                  WHERE m.usuario_id = %s ORDER BY m.id DESC'''
        cur.execute(consulta_consolidado, (usuario_id,))
        consolidado_db = cur.fetchall()
        for fila in consolidado_db:
            try:
                fila['det_externo'] = json.loads(fila['det_externo']) if fila.get('det_externo') else None
            except Exception:
                fila['det_externo'] = None
        cur.execute('SELECT ss_token, ss_email FROM usuarios WHERE id=%s', (usuario_id,))
        ss_user = cur.fetchone()
        ss_conectado = bool(ss_user and ss_user.get('ss_token'))
        ss_email_conectado = ss_user.get('ss_email') if ss_user else None
        cur.execute('SELECT * FROM usuario_surveys WHERE usuario_id=%s ORDER BY id', (usuario_id,))
        ss_surveys = cur.fetchall()
        cur.execute('SELECT * FROM fincas WHERE usuario_id=%s ORDER BY nombre', (usuario_id,))
        fincas_db = cur.fetchall()
        cur.execute('SELECT * FROM parcelas WHERE usuario_id=%s ORDER BY finca_nombre, nombre', (usuario_id,))
        parcelas_db = cur.fetchall()
        return render_template('index.html', muestras=muestras_db, consolidado=consolidado_db, username=username,
                               ss_conectado=ss_conectado, ss_email_conectado=ss_email_conectado, ss_surveys=ss_surveys,
                               fincas=fincas_db, parcelas=parcelas_db)
    finally:
        cur.close()
        conexion.close()

@app.route('/api/datos_crudos/<int:muestra_id>')
def datos_crudos(muestra_id):
    if 'usuario_id' not in session: return jsonify({"error": "No autorizado"}), 403
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        datos = {}
        cur.execute('SELECT nombre_muestra, cultivo, textura, volumen_sedimentacion, vs_lectura, vs_peso, latitud, longitud, descripcion, informacion_relevante, foto_macrofauna, foto_cromatografia, obs_cromatografia FROM muestras WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        m_row = cur.fetchone()
        if m_row: datos.update({'nombre': m_row['nombre_muestra'], 'cultivo': m_row['cultivo'], 'textura': m_row['textura'], 'volumen_sedimentacion': m_row['volumen_sedimentacion'], 'vs_lectura': m_row['vs_lectura'], 'vs_peso': m_row['vs_peso'], 'latitud': m_row['latitud'], 'longitud': m_row['longitud'], 'descripcion': m_row['descripcion'], 'info': m_row['informacion_relevante'], 'foto_macrofauna': m_row['foto_macrofauna'], 'foto_cromatografia': m_row['foto_cromatografia'], 'obs_cromatografia': m_row['obs_cromatografia']})
        
        cur.execute('SELECT ph, conductividad FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
        ph_row = cur.fetchone()
        if ph_row: datos.update({'ph': ph_row['ph'], 'conductividad': ph_row['conductividad']})
        
        cur.execute('SELECT resultado_carbono, peso_suelo, abs_muestra, abs_1, abs_2, abs_3, abs_4 FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
        c_row = cur.fetchone()
        if c_row: 
            datos.update({'c_peso': c_row['peso_suelo'], 'c_abs': c_row['abs_muestra'], 'c_a1': c_row['abs_1'], 'c_a2': c_row['abs_2'], 'c_a3': c_row['abs_3'], 'c_a4': c_row['abs_4'], 'c_res': c_row['resultado_carbono']})
            try:
                conc = np.array([0.005, 0.01, 0.015, 0.02])
                absor = np.array([float(c_row['abs_1']), float(c_row['abs_2']), float(c_row['abs_3']), float(c_row['abs_4'])])
                res = stats.linregress(absor, conc)
                datos['c_eq'] = f"y = {res.slope:.4f}x + {res.intercept:.4f} (R²={res.rvalue**2:.4f})"
                datos['c_slope'] = res.slope
                datos['c_inter'] = res.intercept
            except: pass
            
        cur.execute('SELECT resultado_ppm, resultado_mg_kg, peso_suelo, vol_extracto, vol_dilucion, abs_muestra, abs_0, abs_01, abs_02, abs_04, abs_06, abs_08 FROM fosforo_olsen WHERE muestra_id = %s', (muestra_id,))
        p_row = cur.fetchone()
        if p_row:
            datos.update({'p_peso': p_row['peso_suelo'], 'p_volext': p_row['vol_extracto'], 'p_voldil': p_row['vol_dilucion'], 'p_abs': p_row['abs_muestra'], 'p_a0': p_row['abs_0'], 'p_a01': p_row['abs_01'], 'p_a02': p_row['abs_02'], 'p_a04': p_row['abs_04'], 'p_a06': p_row['abs_06'], 'p_a08': p_row['abs_08'], 'p_res_mg': p_row['resultado_mg_kg'], 'p_res_ppm': p_row['resultado_ppm']})
            try:
                conc = np.array([0.0, 0.1, 0.2, 0.4, 0.6, 0.8])
                absor = np.array([float(p_row['abs_0']), float(p_row['abs_01']), float(p_row['abs_02']), float(p_row['abs_04']), float(p_row['abs_06']), float(p_row['abs_08'])])
                res = stats.linregress(conc, absor)
                datos['p_eq'] = f"y = {res.slope:.4f}x + {res.intercept:.4f} (R²={res.rvalue**2:.4f})"
                datos['p_slope'] = res.slope
                datos['p_inter'] = res.intercept
            except: pass
            
        cur.execute('SELECT peso_suelo, peso_filtro, peso_muestra_con_filtro FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
        mop_row = cur.fetchone()
        if mop_row: datos.update({'mop_suelo': mop_row['peso_suelo'], 'mop_pf': mop_row.get('peso_filtro'), 'mop_pmcf': mop_row.get('peso_muestra_con_filtro')})
        
        cur.execute('SELECT indice_slakes FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
        ea_row = cur.fetchone()
        if ea_row: datos.update({'ea_slakes': ea_row['indice_slakes']})
        
        cur.execute('SELECT peso_suelo, co2_initial, co2_final, horas, ugc_gsoil, curva_tiempo, curva_co2 FROM respiracion_suelo WHERE muestra_id = %s', (muestra_id,))
        r_row = cur.fetchone()
        if r_row:
            datos.update({'r_peso': r_row['peso_suelo'], 'r_ini': r_row['co2_initial'], 'r_fin': r_row['co2_final'], 'r_horas': r_row['horas'], 'r_res': r_row['ugc_gsoil'], 'r_tiempo': r_row['curva_tiempo'], 'r_co2': r_row['curva_co2']})
            
        return jsonify(datos)
    finally: 
        cur.close()
        conexion.close()

@app.route('/eliminar_muestra/<int:muestra_id>', methods=['POST'])
def eliminar_muestra(muestra_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('DELETE FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM fosforo_olsen WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM respiracion_suelo WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM analisis_externo WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM muestras WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        conexion.commit()
    finally: 
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#consolidado')

@app.route('/informe_externo/<int:muestra_id>')
def informe_externo(muestra_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('''SELECT ae.archivo_pdf, ae.archivo_nombre
                       FROM analisis_externo ae
                       JOIN muestras m ON m.id = ae.muestra_id
                       WHERE ae.muestra_id = %s AND m.usuario_id = %s''',
                    (muestra_id, session['usuario_id']))
        row = cur.fetchone()
        if not row or not row['archivo_pdf']:
            return "Informe no encontrado", 404
        resp = make_response(bytes(row['archivo_pdf']))
        resp.headers['Content-Type'] = 'application/pdf'
        resp.headers['Content-Disposition'] = 'inline; filename="' + (row['archivo_nombre'] or 'informe.pdf') + '"'
        return resp
    finally:
        cur.close()
        conexion.close()

@app.route('/eliminar_analisis_externo/<int:muestra_id>', methods=['POST'])
def eliminar_analisis_externo(muestra_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('''DELETE FROM analisis_externo WHERE muestra_id = %s
                       AND muestra_id IN (SELECT id FROM muestras WHERE usuario_id = %s)''',
                    (muestra_id, session['usuario_id']))
        conexion.commit()
        flash('Análisis externo eliminado.', 'success')
    finally:
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#analisis-externo')

@app.route('/eliminar_foto/<int:muestra_id>', methods=['POST'])
def eliminar_foto(muestra_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('UPDATE muestras SET foto_macrofauna = NULL WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        conexion.commit()
        flash('Foto eliminada correctamente.', 'success')
    finally: 
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#macrofauna')

@app.route('/eliminar_cromo/<int:muestra_id>', methods=['POST'])
def eliminar_cromo(muestra_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('UPDATE muestras SET foto_cromatografia = NULL, obs_cromatografia = NULL WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        conexion.commit()
        flash('Cromatografía eliminada correctamente.', 'success')
    finally: 
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#cromatografia')

def _fmt_csv(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    try:
        fv = float(v)
        formatted = f'{fv:.6f}'.rstrip('0').rstrip('.')
        return formatted.replace('.', ',')
    except (TypeError, ValueError):
        return str(v)

@app.route('/descargar_csv')
def descargar_csv():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    consulta = '''SELECT m.id AS "ID", m.nombre_muestra AS "Muestra", m.cultivo AS "Cultivo", m.textura AS "Textura", m.volumen_sedimentacion AS "Vol_Sedimentacion", m.latitud AS "Latitud", m.longitud AS "Longitud", m.descripcion AS "Descripcion",
                  m.foto_macrofauna AS "Foto_Macrofauna", m.foto_cromatografia AS "Foto_Cromatografia", m.obs_cromatografia AS "Obs_Cromatografia",
                  c.resultado_carbono AS "Carbono_Activo", fo.resultado_ppm AS "Fosforo_ppm", fo.resultado_mg_kg AS "Fosforo_mg_kg",
                  p.ph AS "pH", p.conductividad AS "Conductividad", mo.resultado_porcentaje AS "Mat_Particulada_Porc",
                  ea.indice_slakes AS "Indice_Slakes",
                  rs.ugc_gsoil AS "Respiracion_ugC_g"
                  FROM muestras m
                  LEFT JOIN carbono_activo c ON m.id = c.muestra_id
                  LEFT JOIN fosforo_olsen fo ON m.id = fo.muestra_id
                  LEFT JOIN ph_conductividad p ON m.id = p.muestra_id
                  LEFT JOIN materia_organica mo ON m.id = mo.muestra_id
                  LEFT JOIN estabilidad_agregados ea ON m.id = ea.muestra_id
                  LEFT JOIN respiracion_suelo rs ON m.id = rs.muestra_id
                  WHERE m.usuario_id = %s ORDER BY m.id'''
    cur.execute(consulta, (session['usuario_id'],))
    filas = cur.fetchall()
    nombres_columnas = [col.name for col in cur.description]
    cur.close()
    conexion.close()
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(nombres_columnas)
    for fila in filas:
        writer.writerow([_fmt_csv(v) for v in fila.values()])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=Mis_Datos_Suelos.csv"})

@app.route('/sincronizar_api', methods=['POST'])
def sincronizar_api():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    ss_email = request.form.get('ss_email')
    ss_password = request.form.get('ss_password')
    survey_id = request.form.get('survey_id')
    token = None
    try:
        if ss_email and ss_password:
            auth_url = "https://app.surveystack.io/api/auth/login"
            auth_payload = json.dumps({"email": ss_email, "password": ss_password}).encode('utf-8')
            req_auth = urllib.request.Request(auth_url, data=auth_payload, headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req_auth) as auth_res:
                    auth_data = json.loads(auth_res.read().decode('utf-8'))
                    token = auth_data.get('token')
            except urllib.error.HTTPError:
                flash("Credenciales incorrectas.", "danger")
                return redirect(url_for('inicio') + '#ms-surveystack')

        url_api = f"https://app.surveystack.io/api/submissions?survey={survey_id}"
        headers = {'Content-Type': 'application/json'}
        if token and ss_email: headers['Authorization'] = f"{ss_email} {token}"
            
        req_datos = urllib.request.Request(url_api, headers=headers)
        with urllib.request.urlopen(req_datos) as response: respuesta = response.read().decode('utf-8')
            
        datos_json = json.loads(respuesta)
        if isinstance(datos_json, dict) and 'data' in datos_json: datos_json = datos_json['data']
            
        conexion = obtener_conexion()
        cur = conexion.cursor()
        usuario_actual = session['usuario_id']
        contador = 0
        for fila in datos_json:
            id_unico = fila.get('_id')
            if not id_unico: continue 
            data = fila.get('data', {})
            def extraer(clave): return data.get(clave, {}).get('value')
            
            nombre_crudo = extraer('nombre_muestra') or extraer('id_parcela') or "Muestra"
            nombre_final = f"{str(nombre_crudo).strip()} (#{str(id_unico)[-4:]})"
            cultivo = extraer('cultivo_parcela')
            textura = extraer('tipo_parcela')
            descripcion = extraer('observaciones_muestra')
            info = extraer('fert_parcela')
            
            lat, lon = None, None
            ubicacion = extraer('ubicacion_muestra')
            if ubicacion and isinstance(ubicacion, dict) and 'geometry' in ubicacion:
                coords = ubicacion['geometry'].get('coordinates', [])
                if len(coords) >= 2: lon, lat = coords[0], coords[1] 
                    
            archivo_bruto = extraer('foto_macrofauna')
            url_foto = None
            if archivo_bruto:
                nombre_archivo = archivo_bruto[0] if isinstance(archivo_bruto, list) else archivo_bruto
                url_foto = f"https://surveystack.s3.amazonaws.com/{nombre_archivo}"
            
            cur.execute('''INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, textura, latitud, longitud, descripcion, informacion_relevante, foto_macrofauna) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (usuario_id, nombre_muestra) DO UPDATE SET cultivo = COALESCE(EXCLUDED.cultivo, muestras.cultivo), textura = COALESCE(EXCLUDED.textura, muestras.textura), latitud = COALESCE(EXCLUDED.latitud, muestras.latitud), longitud = COALESCE(EXCLUDED.longitud, muestras.longitud), descripcion = COALESCE(EXCLUDED.descripcion, muestras.descripcion), informacion_relevante = COALESCE(EXCLUDED.informacion_relevante, muestras.informacion_relevante), foto_macrofauna = COALESCE(EXCLUDED.foto_macrofauna, muestras.foto_macrofauna)''', (usuario_actual, nombre_final, cultivo, textura, lat, lon, descripcion, info, url_foto))
            contador += 1
        conexion.commit()
        cur.close()
        conexion.close()
        flash(f'Sincronización exitosa. {contador} muestras importadas.', 'success')
    except Exception as e: flash(f'Error al procesar: {str(e)}', 'danger')
    return redirect(url_for('inicio') + '#ms-surveystack')

def parsear_muestra_suelo(fila):
    data = fila.get('data', {})
    page3 = data.get('page_3', {})
    page2 = data.get('page_2', {})
    id_muestra = page3.get('id_muestra', {}).get('value')
    if not id_muestra:
        return None
    finca_val = page3.get('finca', {}).get('value', [])
    finca = finca_val[0] if isinstance(finca_val, list) and finca_val else None
    cultivo_val = page3.get('cultivo', {}).get('value', [])
    cultivo_full = cultivo_val[0] if isinstance(cultivo_val, list) and cultivo_val else None
    cultivo = cultivo_full.split(' | ')[-1].strip() if cultivo_full else None
    parcela_val = page3.get('parcela', {}).get('value', [])
    parcela = parcela_val[0].split(' | ')[-1].strip() if isinstance(parcela_val, list) and parcela_val else None
    lat, lon = None, None
    coords_data = page2.get('coordenadas', {}).get('value', {})
    if isinstance(coords_data, dict):
        features = coords_data.get('features', [])
        if features:
            geom = features[0].get('geometry', {})
            if geom and geom.get('type') == 'Point':
                coords = geom.get('coordinates', [])
                if len(coords) >= 2:
                    lon, lat = float(coords[0]), float(coords[1])
    profundidad_val = page2.get('profundidad', {}).get('value', [])
    profundidad = profundidad_val[0] if isinstance(profundidad_val, list) and profundidad_val else None
    observaciones = page2.get('observaciones', {}).get('value')
    info_parts = []
    if finca: info_parts.append(f"Finca: {finca}")
    if parcela: info_parts.append(f"Parcela: {parcela}")
    if profundidad: info_parts.append(f"Prof.: {profundidad}")
    return {
        'id_muestra': id_muestra,
        'cultivo': cultivo,
        'lat': lat,
        'lon': lon,
        'descripcion': observaciones,
        'info': ' | '.join(info_parts) if info_parts else None,
    }

def parsear_productor(fila):
    data = fila.get('data', {})
    ss_id = fila.get('_id')
    common_profile = data.get('common_profile', {})
    caddr = common_profile.get('contact_and_address', {})
    contact = caddr.get('contact', {})
    location = caddr.get('location', {})
    area_data = caddr.get('area', {})
    nombre = (data.get('organization', {}).get('value')
              or contact.get('organization', {}).get('value')
              or contact.get('name', {}).get('value'))
    if not nombre:
        return None
    nombre_productor = contact.get('name', {}).get('value')
    telefono = contact.get('phone', {}).get('value')
    localidad = location.get('city', {}).get('value')
    prov_val = location.get('province', {}).get('value', [])
    provincia = prov_val[0] if isinstance(prov_val, list) and prov_val else None
    geojson_val = area_data.get('value')
    geojson_str = json.dumps(geojson_val) if geojson_val else None
    land = common_profile.get('land', {})
    ha_val = land.get('area', {}).get('total_hectares', {}).get('value', [])
    try:
        hectareas = float(ha_val[0]) if ha_val else None
    except Exception:
        hectareas = None
    tipos_val = common_profile.get('types', {}).get('value', [])
    tipo = ', '.join(tipos_val) if isinstance(tipos_val, list) and tipos_val else None
    return {
        'ss_id': ss_id, 'nombre': nombre, 'productor': nombre_productor,
        'telefono': telefono, 'localidad': localidad, 'provincia': provincia,
        'hectareas': hectareas, 'tipo_produccion': tipo, 'geojson': geojson_str,
    }


def parsear_parcelas(fila):
    data = fila.get('data', {})
    ss_id = fila.get('_id')
    farm_val = data.get('participating', {}).get('farm', {}).get('value', [])
    if isinstance(farm_val, list) and farm_val:
        finca_nombre = farm_val[0]
    elif isinstance(farm_val, str) and farm_val:
        finca_nombre = farm_val
    else:
        return []
    cultivos_por_campo = {}
    for ptype in ['plantings_div_veg', 'plantings_row_crop', 'plantings_cover_crop', 'plantings_tree_crop']:
        pt = data.get(ptype, {})
        if not pt:
            continue
        planting_list = pt.get('planting', {}).get('value', [])
        if not isinstance(planting_list, list):
            continue
        for p in planting_list:
            fields = p.get('field', {}).get('value', [])
            crop_val = p.get('crop', {}).get('value', [])
            crop = crop_val[0] if isinstance(crop_val, list) and crop_val else None
            if not crop:
                continue
            for f in (fields if isinstance(fields, list) else []):
                fname = f.get('name', '') if isinstance(f, dict) else ''
                if fname:
                    cultivos_por_campo.setdefault(fname, set()).add(crop)
    result = []
    for i in range(1, 6):
        fd = data.get(f'create_field_{i}')
        if not fd:
            continue
        add = fd.get('add', {})
        name_data = add.get('name', {}).get('value')
        if isinstance(name_data, dict):
            nombre = name_data.get('name')
        elif isinstance(name_data, str):
            nombre = name_data
        else:
            continue
        if not nombre:
            continue
        area_val = add.get('area', {}).get('value')
        geojson_str = json.dumps(area_val) if area_val else None
        flags_val = add.get('flags', {}).get('value', [])
        certificacion = flags_val[0] if isinstance(flags_val, list) and flags_val else None
        cultivos = list(cultivos_por_campo.get(nombre, set()))
        result.append({
            'ss_id': ss_id, 'finca_nombre': finca_nombre, 'nombre': nombre,
            'nombre_completo': f"{finca_nombre} | {nombre}",
            'certificacion': certificacion,
            'cultivo': ', '.join(cultivos) if cultivos else None,
            'geojson': geojson_str,
        })
    return result


@app.route('/conectar-surveystack', methods=['POST'])
def conectar_surveystack():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    ss_email = request.form.get('ss_email', '').strip()
    ss_password = request.form.get('ss_password', '')
    if not ss_email or not ss_password:
        flash('Email y contraseña son requeridos.', 'danger')
        return redirect(url_for('inicio') + '#ms-surveystack')
    try:
        auth_url = "https://app.surveystack.io/api/auth/login"
        auth_payload = json.dumps({"email": ss_email, "password": ss_password}).encode('utf-8')
        req_auth = urllib.request.Request(auth_url, data=auth_payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req_auth) as auth_res:
            auth_data = json.loads(auth_res.read().decode('utf-8'))
        token = auth_data.get('token')
        if not token:
            flash('No se pudo obtener el token. Verificá tus credenciales.', 'danger')
            return redirect(url_for('inicio') + '#ms-surveystack')
        user_info = auth_data.get('user', {})
        ss_user_id = user_info.get('_id') or auth_data.get('_id')
        conexion = obtener_conexion()
        cur = conexion.cursor()
        cur.execute('UPDATE usuarios SET ss_token=%s, ss_user_id=%s, ss_email=%s WHERE id=%s', (token, ss_user_id, ss_email, session['usuario_id']))
        conexion.commit()
        cur.close()
        conexion.close()
        flash(f'Conectado a SurveyStack como {ss_email}.', 'success')
    except urllib.error.HTTPError:
        flash('Credenciales incorrectas.', 'danger')
    except Exception as e:
        flash(f'Error al conectar: {str(e)}', 'danger')
    return redirect(url_for('inicio') + '#ms-surveystack')

@app.route('/desconectar-surveystack', methods=['POST'])
def desconectar_surveystack():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    cur.execute('UPDATE usuarios SET ss_token=NULL, ss_user_id=NULL, ss_email=NULL WHERE id=%s', (session['usuario_id'],))
    conexion.commit()
    cur.close()
    conexion.close()
    flash('Desconectado de SurveyStack.', 'info')
    return redirect(url_for('inicio') + '#ms-surveystack')

@app.route('/guardar-survey', methods=['POST'])
def guardar_survey():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    nombre = request.form.get('nombre', '').strip()
    survey_id = request.form.get('survey_id', '').strip()
    tipo = request.form.get('tipo', '').strip()
    edit_id = request.form.get('edit_id')
    if not nombre or not survey_id or not tipo:
        flash('Todos los campos son requeridos.', 'danger')
        return redirect(url_for('inicio') + '#ms-surveystack')
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        if edit_id:
            cur.execute('UPDATE usuario_surveys SET nombre=%s, survey_id=%s, tipo=%s WHERE id=%s AND usuario_id=%s', (nombre, survey_id, tipo, edit_id, session['usuario_id']))
        else:
            cur.execute('''INSERT INTO usuario_surveys (usuario_id, nombre, survey_id, tipo) VALUES (%s, %s, %s, %s)
                ON CONFLICT (usuario_id, survey_id) DO UPDATE SET nombre=EXCLUDED.nombre, tipo=EXCLUDED.tipo''', (session['usuario_id'], nombre, survey_id, tipo))
        conexion.commit()
        flash('Encuesta guardada.', 'success')
    except Exception as e:
        conexion.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#ms-surveystack')

@app.route('/eliminar-survey/<int:survey_db_id>', methods=['POST'])
def eliminar_survey(survey_db_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    cur.execute('DELETE FROM usuario_surveys WHERE id=%s AND usuario_id=%s', (survey_db_id, session['usuario_id']))
    conexion.commit()
    cur.close()
    conexion.close()
    flash('Encuesta eliminada.', 'info')
    return redirect(url_for('inicio') + '#ms-surveystack')

@app.route('/importar-survey/<int:survey_db_id>', methods=['POST'])
def importar_survey(survey_db_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    usuario_id = session['usuario_id']
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('SELECT * FROM usuario_surveys WHERE id=%s AND usuario_id=%s', (survey_db_id, usuario_id))
        survey = cur.fetchone()
        if not survey:
            flash('Encuesta no encontrada.', 'danger')
            return redirect(url_for('inicio') + '#ms-surveystack')
        cur.execute('SELECT ss_token, ss_email FROM usuarios WHERE id=%s', (usuario_id,))
        user = cur.fetchone()
        if not user or not user['ss_token']:
            flash('Conectate a SurveyStack primero.', 'warning')
            return redirect(url_for('inicio') + '#ms-surveystack')
        token = user['ss_token']
        ss_email = user['ss_email']
        url_api = f"https://app.surveystack.io/api/submissions?survey={survey['survey_id']}"
        headers = {'Content-Type': 'application/json', 'Authorization': f"{ss_email} {token}"}
        req = urllib.request.Request(url_api, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                respuesta = response.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            if e.code == 401:
                flash('Token vencido. Reconectate a SurveyStack.', 'warning')
            else:
                flash(f'Error al conectar con SurveyStack ({e.code}).', 'danger')
            return redirect(url_for('inicio') + '#ms-surveystack')
        datos_json = json.loads(respuesta)
        if isinstance(datos_json, dict) and 'data' in datos_json:
            datos_json = datos_json['data']
        if not isinstance(datos_json, list):
            flash('Respuesta inesperada de SurveyStack. Verificá el ID de encuesta.', 'danger')
            return redirect(url_for('inicio') + '#ms-surveystack')
        total_recibidos = len(datos_json)
        # Filtrar solo los envíos del usuario autenticado
        ss_email_lower = (ss_email or '').lower()
        mis_envios = [f for f in datos_json if f.get('meta', {}).get('creatorDetail', {}).get('email', '').lower() == ss_email_lower]
        # Si el filtro elimina todo pero hay envíos, la API ya los filtró — usar todos
        if not mis_envios and total_recibidos > 0:
            mis_envios = datos_json
        tipo = survey['tipo']
        contador = 0
        if tipo == 'muestra_suelo':
            for fila in mis_envios:
                resultado = parsear_muestra_suelo(fila)
                if not resultado:
                    continue
                cur.execute('''INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, latitud, longitud, descripcion, informacion_relevante)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (usuario_id, nombre_muestra) DO UPDATE SET
                        cultivo = COALESCE(EXCLUDED.cultivo, muestras.cultivo),
                        latitud = COALESCE(EXCLUDED.latitud, muestras.latitud),
                        longitud = COALESCE(EXCLUDED.longitud, muestras.longitud),
                        descripcion = COALESCE(EXCLUDED.descripcion, muestras.descripcion),
                        informacion_relevante = COALESCE(EXCLUDED.informacion_relevante, muestras.informacion_relevante)''',
                    (usuario_id, resultado['id_muestra'], resultado['cultivo'], resultado['lat'], resultado['lon'], resultado['descripcion'], resultado['info']))
                contador += 1
            conexion.commit()
            if contador > 0:
                flash(f'{contador} muestras de suelo importadas correctamente.', 'success')
            elif total_recibidos == 0:
                flash('No hay envíos en esta encuesta todavía.', 'info')
            else:
                flash(f'Se recibieron {total_recibidos} envíos pero ninguno pudo parsearse. Verificá que el tipo sea correcto.', 'warning')
        elif tipo == 'test_productor':
            for fila in mis_envios:
                resultado = parsear_productor(fila)
                if not resultado:
                    continue
                cur.execute('''INSERT INTO fincas (usuario_id, ss_submission_id, nombre, productor, telefono, localidad, provincia, hectareas, tipo_produccion, geojson)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (usuario_id, ss_submission_id) DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        productor = COALESCE(EXCLUDED.productor, fincas.productor),
                        telefono = COALESCE(EXCLUDED.telefono, fincas.telefono),
                        localidad = COALESCE(EXCLUDED.localidad, fincas.localidad),
                        provincia = COALESCE(EXCLUDED.provincia, fincas.provincia),
                        hectareas = COALESCE(EXCLUDED.hectareas, fincas.hectareas),
                        tipo_produccion = COALESCE(EXCLUDED.tipo_produccion, fincas.tipo_produccion),
                        geojson = COALESCE(EXCLUDED.geojson, fincas.geojson)''',
                    (usuario_id, resultado['ss_id'], resultado['nombre'], resultado['productor'],
                     resultado['telefono'], resultado['localidad'], resultado['provincia'],
                     resultado['hectareas'], resultado['tipo_produccion'], resultado['geojson']))
                contador += 1
            conexion.commit()
            if contador > 0:
                flash(f'{contador} productores/fincas importados correctamente.', 'success')
            elif total_recibidos == 0:
                flash('No hay envíos en esta encuesta todavía.', 'info')
            else:
                flash(f'Se recibieron {total_recibidos} envíos pero ninguno pudo parsearse.', 'warning')
        elif tipo == 'test_parcela':
            for fila in mis_envios:
                for p in parsear_parcelas(fila):
                    cur.execute('''INSERT INTO parcelas (usuario_id, finca_nombre, nombre, nombre_completo, certificacion, cultivo, geojson)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (usuario_id, finca_nombre, nombre) DO UPDATE SET
                            nombre_completo = EXCLUDED.nombre_completo,
                            certificacion = COALESCE(EXCLUDED.certificacion, parcelas.certificacion),
                            cultivo = COALESCE(EXCLUDED.cultivo, parcelas.cultivo),
                            geojson = COALESCE(EXCLUDED.geojson, parcelas.geojson)''',
                        (usuario_id, p['finca_nombre'], p['nombre'], p['nombre_completo'],
                         p['certificacion'], p['cultivo'], p['geojson']))
                    contador += 1
            conexion.commit()
            if contador > 0:
                flash(f'{contador} parcelas importadas correctamente.', 'success')
            elif total_recibidos == 0:
                flash('No hay envíos en esta encuesta todavía.', 'info')
            else:
                flash(f'Se recibieron {total_recibidos} envíos pero no se encontraron parcelas válidas.', 'warning')
        else:
            flash(f'Tipo de encuesta "{tipo}" no reconocido.', 'warning')
    except Exception as e:
        conexion.rollback()
        flash(f'Error al importar: {str(e)}', 'danger')
    finally:
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#ms-surveystack')

@app.route('/eliminar_finca/<int:finca_id>', methods=['POST'])
def eliminar_finca(finca_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('DELETE FROM fincas WHERE id=%s AND usuario_id=%s', (finca_id, session['usuario_id']))
        conexion.commit()
        flash('Productor/finca eliminado.', 'info')
    finally:
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#consolidado')

@app.route('/eliminar_parcela/<int:parcela_id>', methods=['POST'])
def eliminar_parcela(parcela_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('DELETE FROM parcelas WHERE id=%s AND usuario_id=%s', (parcela_id, session['usuario_id']))
        conexion.commit()
        flash('Parcela eliminada.', 'info')
    finally:
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#consolidado')

@app.route('/api/metodos')
def api_metodos():
    with open('metodos_laboratorios.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "name": "Lab Agroecológico",
        "short_name": "LabAgro",
        "description": "Plataforma de seguimiento de análisis de suelo agroecológico",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f8f9fa",
        "theme_color": "#2d6a4f",
        "lang": "es",
        "icons": [
            {
                "src": "/static/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/static/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    response = make_response(jsonify(manifest_data))
    response.headers["Content-Type"] = "application/json"
    return response

@app.route('/sw.js')
def sw():
    sw_content = """
    const CACHE_NAME = 'agro-cache-v7';
    const urlsToCache = ['/'];
    self.addEventListener('install', (e) => { 
        e.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(urlsToCache)));
        self.skipWaiting(); 
    }); 
    self.addEventListener('activate', (e) => {
        e.waitUntil(caches.keys().then(keyList => {
            return Promise.all(keyList.map(key => { if(key !== CACHE_NAME) return caches.delete(key); }));
        }));
        self.clients.claim();
    });
    self.addEventListener('fetch', (e) => { 
        if (e.request.method !== 'GET') return;
        e.respondWith(
            fetch(e.request)
            .then(response => {
                const resClone = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(e.request, resClone));
                return response;
            })
            .catch(() => caches.match(e.request).then(res => res || caches.match('/')))
        );
    });
    """
    response = make_response(sw_content)
    response.headers['Content-Type'] = 'application/javascript'
    return response

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
