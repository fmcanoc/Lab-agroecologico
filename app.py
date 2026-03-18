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

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'clave_super_secreta_trazabilidad_suelos'

def obtener_conexion():
    url_bd = os.environ.get('DATABASE_URL', '***REMOVED_DB_URI***')
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
                            abs_0 NUMERIC, abs_05 NUMERIC, abs_1 NUMERIC, abs_15 NUMERIC, abs_2 NUMERIC)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS respiracion_suelo (
                            id SERIAL PRIMARY KEY, muestra_id INTEGER REFERENCES muestras(id) ON DELETE CASCADE, 
                            peso_suelo NUMERIC, co2_initial NUMERIC, co2_final NUMERIC, horas NUMERIC, ugc_gsoil NUMERIC, 
                            curva_tiempo TEXT, curva_co2 TEXT)''')
            conexion.commit()
            
            # Agregado de columnas para fotos si no existen
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

            conexion.commit()
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
        cur.execute('INSERT INTO usuarios (username, password) VALUES (%s, %s)', (username, hashed_password))
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
                textura = request.form.get('textura')
                lat_str, lon_str = request.form.get('latitud'), request.form.get('longitud')
                latitud = float(lat_str) if lat_str else None
                longitud = float(lon_str) if lon_str else None
                muestra_id_editar = request.form.get('muestra_id_editar')
                if muestra_id_editar:
                    cur.execute('''UPDATE muestras SET nombre_muestra=%s, cultivo=%s, textura=%s, latitud=%s, longitud=%s, descripcion=%s, informacion_relevante=%s WHERE id=%s AND usuario_id=%s''', (nombre, cultivo, textura, latitud, longitud, descripcion, info, muestra_id_editar, usuario_id))
                    flash('Muestra actualizada exitosamente.', 'info')
                else:
                    try:
                        cur.execute('''INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, textura, descripcion, informacion_relevante, latitud, longitud) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', (usuario_id, nombre, cultivo, textura, descripcion, info, latitud, longitud))
                        flash('Muestra creada exitosamente.', 'success')
                    except errors.UniqueViolation:
                        conexion.rollback()
                        cur.execute('''UPDATE muestras SET cultivo=%s, textura=%s, descripcion=%s, informacion_relevante=%s, latitud=%s, longitud=%s WHERE usuario_id=%s AND nombre_muestra=%s''', (cultivo, textura, descripcion, info, latitud, longitud, usuario_id, nombre))
                        flash('Muestra actualizada exitosamente.', 'info')
                conexion.commit()
                return redirect(url_for('inicio') + '#muestras')
                
            if not muestra_id and tipo_formulario != 'registro_muestra':
                 return redirect(url_for('inicio'))

            if tipo_formulario == 'textura_suelo':
                cur.execute('UPDATE muestras SET textura = %s WHERE id = %s AND usuario_id = %s', (request.form['textura'], muestra_id, usuario_id))
                conexion.commit()
                flash('Textura guardada exitosamente.', 'success')
                return redirect(url_for('inicio') + '#textura')

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
                return redirect(url_for('inicio') + '#respiracion')

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
                flash('POXC Calculado.', 'success')
                return redirect(url_for('inicio') + '#carbono')

            elif tipo_formulario == 'fosforo_olsen':
                peso_g, vol_ext, vol_dil = float(request.form.get('peso_suelo', 2.5)), float(request.form.get('vol_extracto', 7.0)), float(request.form.get('vol_dilucion', 20.0))
                abs_m, a0, a05, a1, a15, a2 = float(request.form['abs_muestra']), float(request.form['abs_0']), float(request.form['abs_05']), float(request.form['abs_1']), float(request.form['abs_15']), float(request.form['abs_2'])
                conc = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
                absor = np.array([a0, a05, a1, a15, a2])
                resultado = stats.linregress(conc, absor)
                ppm = abs_m / resultado.slope if resultado.slope != 0 else 0
                p_disponible = (((ppm * 0.0559) - 0.052) * (vol_dil / vol_ext) * 0.025) / (peso_g / 1000)
                cur.execute('DELETE FROM fosforo_olsen WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO fosforo_olsen (muestra_id, resultado_ppm, resultado_mg_kg, peso_suelo, vol_extracto, vol_dilucion, abs_muestra, abs_0, abs_05, abs_1, abs_15, abs_2) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', (muestra_id, ppm, p_disponible, peso_g, vol_ext, vol_dil, abs_m, a0, a05, a1, a15, a2))
                conexion.commit()
                flash('Fósforo calculado.', 'success')
                return redirect(url_for('inicio') + '#fosforo')

            elif tipo_formulario == 'ph_conductividad':
                cur.execute('DELETE FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
                cur.execute('INSERT INTO ph_conductividad (muestra_id, ph, conductividad) VALUES (%s, %s, %s)', (muestra_id, float(request.form['ph']), float(request.form['conductividad'])))
                conexion.commit()
                flash('pH y Conductividad guardados.', 'success')
                return redirect(url_for('inicio') + '#ph')

            elif tipo_formulario == 'materia_organica':
                pf_mop, pm_filtro, ps = float(request.form['peso_filtro_mop']), float(request.form['peso_muestra_con_filtro']), float(request.form['peso_suelo'])
                pp_neto = pm_filtro - pf_mop
                mop_porcentaje = pp_neto / (ps * 10)
                cur.execute('DELETE FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO materia_organica (muestra_id, resultado_porcentaje, peso_particulas, peso_suelo, peso_filtro, peso_muestra_con_filtro) VALUES (%s, %s, %s, %s, %s, %s)''', (muestra_id, mop_porcentaje, pp_neto, ps, pf_mop, pm_filtro))
                conexion.commit()
                flash('MOP calculado.', 'success')
                return redirect(url_for('inicio') + '#mop')

            elif tipo_formulario == 'estabilidad_agregados':
                pi, pf, tara_piedras, piedras_bruto, pm, p250 = float(request.form['peso_inicial']), float(request.form['peso_filtro']), float(request.form['peso_recipiente_piedras']), float(request.form['peso_piedras_con_recipiente']), float(request.form['peso_fraccion_mayor']), float(request.form['peso_fraccion_250'])
                ppd_neto = piedras_bruto - tara_piedras
                denominador = pi - ppd_neto
                porc_mayor = ((pm - pf) / denominador) * 100
                porc_250 = ((p250 - pf) / denominador) * 100
                cur.execute('DELETE FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO estabilidad_agregados (muestra_id, porcentaje_mayor_2mm, porcentaje_250_2mm, peso_inicial, peso_filtro, peso_piedras, peso_fraccion_mayor, peso_fraccion_250, peso_recipiente_piedras, peso_piedras_con_recipiente) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', (muestra_id, porc_mayor, porc_250, pi, pf, ppd_neto, pm, p250, tara_piedras, piedras_bruto))
                conexion.commit()
                flash('Estabilidad calculada.', 'success')
                return redirect(url_for('inicio') + '#estab')

            elif tipo_formulario == 'macrofauna':
                url_foto_manual = request.form.get('foto_macrofauna')
                if not url_foto_manual:
                    flash('Debes esperar a que la foto suba.', 'danger')
                    return redirect(url_for('inicio') + '#macrofauna')
                cur.execute('''UPDATE muestras SET foto_macrofauna = %s WHERE id = %s AND usuario_id = %s''', (url_foto_manual, muestra_id, usuario_id))
                conexion.commit()
                flash('Foto de macrofauna guardada.', 'success')
                return redirect(url_for('inicio') + '#macrofauna')

            elif tipo_formulario == 'cromatografia':
                url_foto_cromo = request.form.get('foto_cromatografia')
                obs_cromo = request.form.get('obs_cromatografia')
                if not url_foto_cromo and not obs_cromo:
                    flash('Debes adjuntar al menos una foto u observación.', 'danger')
                    return redirect(url_for('inicio') + '#cromatografia')
                cur.execute('''UPDATE muestras SET foto_cromatografia = %s, obs_cromatografia = %s WHERE id = %s AND usuario_id = %s''', (url_foto_cromo, obs_cromo, muestra_id, usuario_id))
                conexion.commit()
                flash('Registro de Cromatografía guardado.', 'success')
                return redirect(url_for('inicio') + '#cromatografia')

        cur.execute('SELECT id, nombre_muestra FROM muestras WHERE usuario_id = %s ORDER BY id DESC', (usuario_id,))
        muestras_db = cur.fetchall()
        consulta_consolidado = '''SELECT m.id, m.nombre_muestra, m.cultivo, m.textura, m.descripcion, m.informacion_relevante, m.latitud, m.longitud, m.foto_macrofauna, 
                                  m.foto_cromatografia, m.obs_cromatografia,
                                  c.resultado_carbono, p.ph, p.conductividad, mo.resultado_porcentaje AS mop, 
                                  ea.porcentaje_mayor_2mm, ea.porcentaje_250_2mm, fo.resultado_mg_kg AS fosforo, fo.resultado_ppm AS fosforo_ppm,
                                  rs.ugc_gsoil AS respiracion, rs.co2_initial, rs.co2_final, rs.curva_tiempo, rs.curva_co2
                                  FROM muestras m 
                                  LEFT JOIN carbono_activo c ON m.id = c.muestra_id 
                                  LEFT JOIN ph_conductividad p ON m.id = p.muestra_id 
                                  LEFT JOIN materia_organica mo ON m.id = mo.muestra_id 
                                  LEFT JOIN estabilidad_agregados ea ON m.id = ea.muestra_id 
                                  LEFT JOIN fosforo_olsen fo ON m.id = fo.muestra_id
                                  LEFT JOIN respiracion_suelo rs ON m.id = rs.muestra_id
                                  WHERE m.usuario_id = %s ORDER BY m.id DESC'''
        cur.execute(consulta_consolidado, (usuario_id,))
        consolidado_db = cur.fetchall()
        return render_template('index.html', muestras=muestras_db, consolidado=consolidado_db, username=username)
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
        cur.execute('SELECT nombre_muestra, cultivo, textura, latitud, longitud, descripcion, informacion_relevante, foto_macrofauna, foto_cromatografia, obs_cromatografia FROM muestras WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        m_row = cur.fetchone()
        if m_row: datos.update({'nombre': m_row['nombre_muestra'], 'cultivo': m_row['cultivo'], 'textura': m_row['textura'], 'latitud': m_row['latitud'], 'longitud': m_row['longitud'], 'descripcion': m_row['descripcion'], 'info': m_row['informacion_relevante'], 'foto_macrofauna': m_row['foto_macrofauna'], 'foto_cromatografia': m_row['foto_cromatografia'], 'obs_cromatografia': m_row['obs_cromatografia']})
        cur.execute('SELECT ph, conductividad FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
        ph_row = cur.fetchone()
        if ph_row: datos.update({'ph': ph_row['ph'], 'conductividad': ph_row['conductividad']})
        cur.execute('SELECT peso_suelo, abs_muestra, abs_1, abs_2, abs_3, abs_4 FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
        c_row = cur.fetchone()
        if c_row: datos.update({'c_peso': c_row['peso_suelo'], 'c_abs': c_row['abs_muestra'], 'c_a1': c_row['abs_1'], 'c_a2': c_row['abs_2'], 'c_a3': c_row['abs_3'], 'c_a4': c_row['abs_4']})
        cur.execute('SELECT peso_suelo, vol_extracto, vol_dilucion, abs_muestra, abs_0, abs_05, abs_1, abs_15, abs_2 FROM fosforo_olsen WHERE muestra_id = %s', (muestra_id,))
        p_row = cur.fetchone()
        if p_row: datos.update({'p_peso': p_row['peso_suelo'], 'p_volext': p_row['vol_extracto'], 'p_voldil': p_row['vol_dilucion'], 'p_abs': p_row['abs_muestra'], 'p_a0': p_row['abs_0'], 'p_a05': p_row['abs_05'], 'p_a1': p_row['abs_1'], 'p_a15': p_row['abs_15'], 'p_a2': p_row['abs_2']})
        cur.execute('SELECT peso_suelo, peso_filtro, peso_muestra_con_filtro FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
        mop_row = cur.fetchone()
        if mop_row: datos.update({'mop_suelo': mop_row['peso_suelo'], 'mop_pf': mop_row.get('peso_filtro'), 'mop_pmcf': mop_row.get('peso_muestra_con_filtro')})
        cur.execute('SELECT peso_inicial, peso_filtro, peso_fraccion_mayor, peso_fraccion_250, peso_recipiente_piedras, peso_piedras_con_recipiente FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
        ea_row = cur.fetchone()
        if ea_row: datos.update({'ea_pi': ea_row['peso_inicial'], 'ea_pf': ea_row['peso_filtro'], 'ea_pm': ea_row['peso_fraccion_mayor'], 'ea_p250': ea_row['peso_fraccion_250'], 'ea_rec_p': ea_row.get('peso_recipiente_piedras'), 'ea_pcr': ea_row.get('peso_piedras_con_recipiente')})
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
        cur.execute('DELETE FROM muestras WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        conexion.commit()
    finally: 
        cur.close()
        conexion.close()
    return redirect(url_for('inicio') + '#consolidado')

@app.route('/eliminar_foto/<int:muestra_id>', methods=['POST'])
def eliminar_foto(muestra_id):
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    try:
        cur.execute('UPDATE muestras SET foto_macrofauna = NULL WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        conexion.commit()
        flash('Foto de macrofauna eliminada correctamente.', 'success')
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

@app.route('/descargar_csv')
def descargar_csv():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    cur = conexion.cursor()
    consulta = '''SELECT m.id AS "ID", m.nombre_muestra AS "Muestra", m.cultivo AS "Cultivo", m.textura AS "Textura", m.latitud AS "Latitud", m.longitud AS "Longitud", m.descripcion AS "Descripcion", 
                  m.foto_macrofauna AS "Foto_Macrofauna", m.foto_cromatografia AS "Foto_Cromatografia", m.obs_cromatografia AS "Obs_Cromatografia",
                  c.resultado_carbono AS "Carbono_Activo", fo.resultado_ppm AS "Fosforo_ppm", fo.resultado_mg_kg AS "Fosforo_mg_kg", 
                  p.ph AS "pH", p.conductividad AS "Conductividad", mo.resultado_porcentaje AS "Mat_Particulada_Porc", 
                  ea.porcentaje_mayor_2mm AS "Agregados_Mayor_2mm_Porc", ea.porcentaje_250_2mm AS "Agregados_250_2mm_Porc",
                  rs.ugc_gsoil AS "Respiracion_ugC_g"
                  FROM muestras m 
                  LEFT JOIN carbono_activo c ON m.id = c.muestra_id 
                  LEFT JOIN fosforo_olsen fo ON m.id = fo.muestra_id 
                  LEFT JOIN ph_conductividad p ON m.id = p.muestra_id 
                  LEFT JOIN materia_organica mo ON m.id = mo.muestra_id 
                  LEFT JOIN estabilidad_agregados ea ON m.id = ea.muestra_id 
                  LEFT JOIN respiracion_suelo rs ON m.id = rs.muestra_id
                  WHERE m.usuario_id = %s'''
    cur.execute(consulta, (session['usuario_id'],))
    filas = cur.fetchall()
    nombres_columnas = [col.name for col in cur.description]
    cur.close()
    conexion.close()
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(nombres_columnas)
    for fila in filas: writer.writerow(list(fila.values()))
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
                return redirect(url_for('inicio') + '#muestras')

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
    return redirect(url_for('inicio') + '#muestras')

@app.route('/manifest.json')
def manifest():
    manifest_data = { "name": "Lab Agroecológico", "short_name": "LabAgro", "start_url": "/", "display": "standalone", "background_color": "#f8f9fa", "theme_color": "#2d6a4f", "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/2875/2875078.png", "sizes": "512x512", "type": "image/png"}] }
    response = make_response(jsonify(manifest_data))
    response.headers["Content-Type"] = "application/json"
    return response

@app.route('/sw.js')
def sw():
    sw_content = """
    const CACHE_NAME = 'agro-cache-v6';
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
    app.run(debug=True)
