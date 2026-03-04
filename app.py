import os
import numpy as np
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
import csv
import urllib.request

# Psycopg 3
import psycopg
from psycopg.rows import dict_row
from psycopg import errors

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'clave_super_secreta_trazabilidad_suelos' 

def obtener_conexion():
    url_bd = os.environ.get('DATABASE_URL', '***REMOVED_DB_URI***')
    conexion = psycopg.connect(url_bd, row_factory=dict_row)
    return conexion

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
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_id = session['usuario_id']
    username = session['username']
    conexion = obtener_conexion()
    cur = conexion.cursor()
    
    plot_url = None 
    poxc_calculado = None 
    anchor = "" # Para persistencia de pestañas (Punto 4)
    
    try:
        if request.method == 'POST':
            tipo_formulario = request.form.get('form_type')
            
            if tipo_formulario == 'registro_muestra':
                anchor = "#muestras"
                nombre, cultivo, descripcion, info = request.form['nombre'], request.form['cultivo'], request.form['descripcion'], request.form['info']
                textura = request.form.get('textura') 
                lat_s, lon_s = request.form.get('latitud'), request.form.get('longitud')
                latitud = float(lat_s) if lat_s and lat_s.strip() else None
                longitud = float(lon_s) if lon_s and lon_s.strip() else None
                
                try:
                    cur.execute('''INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, textura, descripcion, informacion_relevante, latitud, longitud) 
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', 
                                (usuario_id, nombre, cultivo, textura, descripcion, info, latitud, longitud))
                except errors.UniqueViolation: 
                    conexion.rollback() 
                    cur.execute('''UPDATE muestras SET cultivo=%s, textura=%s, descripcion=%s, informacion_relevante=%s, latitud=%s, longitud=%s 
                                   WHERE usuario_id=%s AND nombre_muestra=%s''', 
                                (cultivo, textura, descripcion, info, latitud, longitud, usuario_id, nombre))
                conexion.commit()
                return redirect(url_for('inicio') + anchor)
                
            elif tipo_formulario == 'carbono_activo':
                anchor = "#carbono"
                muestra_id = request.form['muestra_id']
                peso_g = float(request.form.get('peso_suelo_carbono', 2.5))
                a1, a2, a3, a4 = float(request.form['abs_1']), float(request.form['abs_2']), float(request.form['abs_3']), float(request.form['abs_4'])
                abs_m = float(request.form['abs_muestra'])
                conc = np.array([0.005, 0.01, 0.015, 0.02]); absor = np.array([a1, a2, a3, a4])
                res = stats.linregress(absor, conc)
                poxc = (0.02 - (res.intercept + (res.slope * abs_m))) * 9000 * (0.02 / (peso_g/1000))
                cur.execute('DELETE FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
                cur.execute('INSERT INTO carbono_activo (muestra_id, resultado_carbono, peso_suelo, abs_muestra, abs_1, abs_2, abs_3, abs_4) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)', (muestra_id, poxc, peso_g, abs_m, a1, a2, a3, a4))
                conexion.commit()
                flash('POXC Calculado', 'success')
                return redirect(url_for('inicio') + anchor)

            elif tipo_formulario == 'ph_conductividad':
                anchor = "#ph"
                muestra_id = request.form['muestra_id']
                cur.execute('DELETE FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
                cur.execute('INSERT INTO ph_conductividad (muestra_id, ph, conductividad) VALUES (%s, %s, %s)', (muestra_id, float(request.form['ph']), float(request.form['conductividad'])))
                conexion.commit()
                return redirect(url_for('inicio') + anchor)

            elif tipo_formulario == 'materia_organica':
                anchor = "#mop"
                muestra_id = request.form['muestra_id']
                pp, ps = float(request.form['peso_particulas']), float(request.form['peso_suelo'])
                mop = pp / (ps * 10)
                cur.execute('DELETE FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
                cur.execute('INSERT INTO materia_organica (muestra_id, resultado_porcentaje, peso_particulas, peso_suelo) VALUES (%s, %s, %s, %s)', (muestra_id, mop, pp, ps))
                conexion.commit()
                return redirect(url_for('inicio') + anchor)

        cur.execute('SELECT id, nombre_muestra FROM muestras WHERE usuario_id = %s', (usuario_id,))
        muestras_db = cur.fetchall()
        
        # PUNTO 1: Consulta completa para el dashboard
        consulta_consolidado = '''SELECT m.*, c.resultado_carbono, p.ph, p.conductividad, mo.resultado_porcentaje AS mop, 
                                  ea.porcentaje_mayor_2mm, ea.porcentaje_250_2mm 
                                  FROM muestras m 
                                  LEFT JOIN carbono_activo c ON m.id = c.muestra_id 
                                  LEFT JOIN ph_conductividad p ON m.id = p.muestra_id 
                                  LEFT JOIN materia_organica mo ON m.id = mo.muestra_id 
                                  LEFT JOIN estabilidad_agregados ea ON m.id = ea.muestra_id 
                                  WHERE m.usuario_id = %s ORDER BY m.id DESC'''
        cur.execute(consulta_consolidado, (usuario_id,))
        consolidado_db = cur.fetchall()
        
        return render_template('index.html', muestras=muestras_db, consolidado=consolidado_db, username=username)
    finally:
        cur.close()
        conexion.close()

@app.route('/api/datos_crudos/<int:muestra_id>')
def datos_crudos(muestra_id):
    conexion = obtener_conexion(); cur = conexion.cursor()
    try:
        datos = {}
        cur.execute('SELECT * FROM muestras WHERE id = %s', (muestra_id,))
        m = cur.fetchone()
        if m: datos.update({'nombre': m['nombre_muestra'], 'cultivo': m['cultivo'], 'textura': m['textura'], 'latitud': m['latitud'], 'longitud': m['longitud'], 'descripcion': m['descripcion'], 'info': m['informacion_relevante']})
        cur.execute('SELECT * FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
        p = cur.fetchone()
        if p: datos.update({'ph': p['ph'], 'conductividad': p['conductividad']})
        cur.execute('SELECT * FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
        c = cur.fetchone()
        if c: datos.update({'c_abs': c['abs_muestra'], 'c_a1': c['abs_1'], 'c_a2': c['abs_2'], 'c_a3': c['abs_3'], 'c_a4': c['abs_4']})
        return jsonify(datos)
    finally:
        cur.close(); conexion.close()

@app.route('/descargar_csv')
def descargar_csv():
    conexion = obtener_conexion(); cur = conexion.cursor()
    # PUNTO 6: Query que trae datos reales
    cur.execute('''SELECT m.nombre_muestra, m.ph, p.conductividad, c.resultado_carbono 
                   FROM muestras m 
                   LEFT JOIN ph_conductividad p ON m.id = p.muestra_id 
                   LEFT JOIN carbono_activo c ON m.id = c.muestra_id 
                   WHERE m.usuario_id = %s''', (session['usuario_id'],))
    filas = cur.fetchall()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Muestra', 'pH', 'Cond', 'Carbono'])
    for f in filas:
        writer.writerow([f['nombre_muestra'], f['ph'], f['conductividad'], f['resultado_carbono']])
    cur.close(); conexion.close()
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=muestras.csv"})

@app.route('/sincronizar_api', methods=['POST'])
def sincronizar_api():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    url_api = "https://app.surveystack.io/api/submissions/csv?survey=69a78356a519d930190644d0&expandAllMatrices=true"
    try:
        req = urllib.request.Request(url_api, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            lineas = response.read().decode('utf-8').splitlines()
        idx = 0
        for i, l in enumerate(lineas):
            if '_id' in l: idx = i; break
        lector = csv.DictReader(io.StringIO("\n".join(lineas[idx:])), delimiter=',')
        conexion = obtener_conexion(); cur = conexion.cursor(); usuario_actual = session['usuario_id']
        for fila in lector:
            id_u = fila.get('_id')
            nombre = fila.get('data.nombre_muestra') or "Muestra"
            n_final = f"{nombre} (#{id_u[-4:]})"
            # PUNTO 3: Mapeo de GPS y Descripción
            cur.execute('''INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, textura, latitud, longitud, descripcion) 
                           VALUES (%s,%s,%s,%s,%s,%s,%s) 
                           ON CONFLICT (usuario_id, nombre_muestra) DO UPDATE SET 
                           latitud=EXCLUDED.latitud, longitud=EXCLUDED.longitud, descripcion=EXCLUDED.descripcion''', 
                        (usuario_actual, n_final, fila.get('data.cultivo'), fila.get('data.textura'), fila.get('data.latitud'), fila.get('data.longitud'), fila.get('data.descripcion')))
        conexion.commit(); cur.close(); conexion.close()
        flash('Sincronización exitosa', 'success')
    except Exception as e: flash(f'Error: {e}', 'danger')
    return redirect(url_for('inicio') + "#muestras")

@app.route('/eliminar_muestra/<int:muestra_id>', methods=['POST'])
def eliminar_muestra(muestra_id):
    conexion = obtener_conexion(); cur = conexion.cursor()
    cur.execute('DELETE FROM muestras WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
    conexion.commit(); cur.close(); conexion.close()
    return redirect(url_for('inicio') + "#consolidado")

if __name__ == '__main__':
    app.run(debug=True)





