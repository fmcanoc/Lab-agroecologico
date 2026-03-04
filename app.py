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

# NUEVA LIBRERÍA: Psycopg 3
import psycopg
from psycopg.rows import dict_row
from psycopg import errors

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'clave_super_secreta_trazabilidad_suelos' 

def obtener_conexion():
    # PEGA AQUÍ TU URL COMPLETA DE NEON (asegúrate de que termine en ?sslmode=require)
    # Fíjate cómo el usuario ahora tiene el "ep-raspy..." seguido de un $ y luego el nombre de usuario
    url_bd = os.environ.get('DATABASE_URL', '***REMOVED_DB_URI***')
    # Psycopg 3 usa row_factory para que los resultados funcionen como diccionarios
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
    
    try:
        if request.method == 'POST':
            tipo_formulario = request.form.get('form_type')
            
            if tipo_formulario == 'registro_muestra':
                nombre, cultivo, descripcion, info = request.form['nombre'], request.form['cultivo'], request.form['descripcion'], request.form['info']
                textura = request.form.get('textura') 
                lat_str, lon_str = request.form.get('latitud'), request.form.get('longitud')
                latitud = float(lat_str) if lat_str else None
                longitud = float(lon_str) if lon_str else None
                
                try:
                    cur.execute('''INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, textura, descripcion, informacion_relevante, latitud, longitud) 
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', 
                                (usuario_id, nombre, cultivo, textura, descripcion, info, latitud, longitud))
                    flash('Muestra creada exitosamente.', 'success')
                except errors.UniqueViolation: 
                    conexion.rollback() 
                    cur.execute('''UPDATE muestras SET cultivo=%s, textura=%s, descripcion=%s, informacion_relevante=%s, latitud=%s, longitud=%s 
                                   WHERE usuario_id=%s AND nombre_muestra=%s''', 
                                (cultivo, textura, descripcion, info, latitud, longitud, usuario_id, nombre))
                    flash('Muestra actualizada exitosamente.', 'info')
                conexion.commit()
                return redirect(url_for('inicio'))
                
            elif tipo_formulario == 'carbono_activo':
                muestra_id = request.form['muestra_id']
                peso_g = float(request.form.get('peso_suelo_carbono', 2.5))
                peso_kg = peso_g / 1000
                a1, a2, a3, a4 = float(request.form['abs_1']), float(request.form['abs_2']), float(request.form['abs_3']), float(request.form['abs_4'])
                abs_m = float(request.form['abs_muestra'])
                
                conc = np.array([0.005, 0.01, 0.015, 0.02])
                absor = np.array([a1, a2, a3, a4])
                resultado = stats.linregress(absor, conc)
                poxc = (0.02 - (resultado.intercept + (resultado.slope * abs_m))) * 9000 * (0.02 / peso_kg)
                
                cur.execute('DELETE FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO carbono_activo (muestra_id, resultado_carbono, peso_suelo, abs_muestra, abs_1, abs_2, abs_3, abs_4) 
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', 
                            (muestra_id, poxc, peso_g, abs_m, a1, a2, a3, a4))
                conexion.commit()
                poxc_calculado = poxc 
                
                plt.figure(figsize=(6, 4))
                plt.scatter(absor, conc, color='blue', label='Datos medidos')
                plt.plot(np.linspace(min(absor), max(absor), 100), resultado.intercept + resultado.slope * np.linspace(min(absor), max(absor), 100), color='red', label='Regresión lineal')
                plt.title('Curva de Calibración (POXC)')
                plt.xlabel('Absorbancia')
                plt.ylabel('Concentración')
                texto_eq = f"y = {resultado.slope:.4f}x + {resultado.intercept:.4f}\nR² = {resultado.rvalue**2:.4f}"
                plt.annotate(texto_eq, xy=(0.05, 0.80), xycoords='axes fraction', bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.9))
                plt.legend()
                plt.tight_layout()
                img = io.BytesIO()
                plt.savefig(img, format='png')
                img.seek(0)
                plot_url = base64.b64encode(img.getvalue()).decode('utf8')
                plt.close()

            elif tipo_formulario == 'ph_conductividad':
                muestra_id = request.form['muestra_id']
                cur.execute('DELETE FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
                cur.execute('INSERT INTO ph_conductividad (muestra_id, ph, conductividad) VALUES (%s, %s, %s)', 
                            (muestra_id, float(request.form['ph']), float(request.form['conductividad'])))
                conexion.commit()
                flash('pH y Conductividad guardados.', 'success')
                return redirect(url_for('inicio'))

            elif tipo_formulario == 'materia_organica':
                muestra_id = request.form['muestra_id']
                pp, ps = float(request.form['peso_particulas']), float(request.form['peso_suelo'])
                mop_porcentaje = pp / (ps * 10)
                cur.execute('DELETE FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
                cur.execute('INSERT INTO materia_organica (muestra_id, resultado_porcentaje, peso_particulas, peso_suelo) VALUES (%s, %s, %s, %s)', 
                            (muestra_id, mop_porcentaje, pp, ps))
                conexion.commit()
                flash('Resultado MOP guardado.', 'success')
                return redirect(url_for('inicio'))

            elif tipo_formulario == 'estabilidad_agregados':
                muestra_id = request.form['muestra_id']
                pi, pf, ppd, pm, p250 = float(request.form['peso_inicial']), float(request.form['peso_filtro']), float(request.form['peso_piedras']), float(request.form['peso_fraccion_mayor']), float(request.form['peso_fraccion_250'])
                denominador = pi - ppd
                porc_mayor = ((pm - pf) / denominador) * 100
                porc_250 = ((p250 - pf) / denominador) * 100
                cur.execute('DELETE FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
                cur.execute('''INSERT INTO estabilidad_agregados (muestra_id, porcentaje_mayor_2mm, porcentaje_250_2mm, peso_inicial, peso_filtro, peso_piedras, peso_fraccion_mayor, peso_fraccion_250) 
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', 
                            (muestra_id, porc_mayor, porc_250, pi, pf, ppd, pm, p250))
                conexion.commit()
                flash('Estabilidad de agregados guardada.', 'success')
                return redirect(url_for('inicio'))

        cur.execute('SELECT id, nombre_muestra FROM muestras WHERE usuario_id = %s', (usuario_id,))
        muestras_db = cur.fetchall()
        
        consulta_consolidado = '''SELECT m.id, m.nombre_muestra, m.cultivo, m.textura, m.descripcion, m.informacion_relevante, m.latitud, m.longitud, 
                                  c.resultado_carbono, p.ph, p.conductividad, mo.resultado_porcentaje AS mop, 
                                  ea.porcentaje_mayor_2mm, ea.porcentaje_250_2mm 
                                  FROM muestras m 
                                  LEFT JOIN carbono_activo c ON m.id = c.muestra_id 
                                  LEFT JOIN ph_conductividad p ON m.id = p.muestra_id 
                                  LEFT JOIN materia_organica mo ON m.id = mo.muestra_id 
                                  LEFT JOIN estabilidad_agregados ea ON m.id = ea.muestra_id 
                                  WHERE m.usuario_id = %s'''
        cur.execute(consulta_consolidado, (usuario_id,))
        consolidado_db = cur.fetchall()
        
        return render_template('index.html', muestras=muestras_db, consolidado=consolidado_db, plot_url=plot_url, poxc_calculado=poxc_calculado, username=username)
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
        cur.execute('SELECT nombre_muestra, cultivo, textura, latitud, longitud, descripcion, informacion_relevante FROM muestras WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        m_row = cur.fetchone()
        if m_row:
            datos.update({
                'nombre': m_row['nombre_muestra'], 'cultivo': m_row['cultivo'], 'textura': m_row['textura'],
                'latitud': m_row['latitud'], 'longitud': m_row['longitud'], 'descripcion': m_row['descripcion'], 'info': m_row['informacion_relevante']
            })
            
        cur.execute('SELECT ph, conductividad FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
        ph_row = cur.fetchone()
        if ph_row: datos.update({'ph': ph_row['ph'], 'conductividad': ph_row['conductividad']})
        
        cur.execute('SELECT peso_suelo, abs_muestra, abs_1, abs_2, abs_3, abs_4 FROM carbono_activo WHERE muestra_id = %s', (muestra_id,))
        c_row = cur.fetchone()
        if c_row: datos.update({'c_peso': c_row['peso_suelo'], 'c_abs': c_row['abs_muestra'], 'c_a1': c_row['abs_1'], 'c_a2': c_row['abs_2'], 'c_a3': c_row['abs_3'], 'c_a4': c_row['abs_4']})
        
        cur.execute('SELECT peso_particulas, peso_suelo FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
        mop_row = cur.fetchone()
        if mop_row: datos.update({'mop_part': mop_row['peso_particulas'], 'mop_suelo': mop_row['peso_suelo']})
        
        cur.execute('SELECT peso_inicial, peso_filtro, peso_piedras, peso_fraccion_mayor, peso_fraccion_250 FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
        ea_row = cur.fetchone()
        if ea_row: datos.update({'ea_pi': ea_row['peso_inicial'], 'ea_pf': ea_row['peso_filtro'], 'ea_pp': ea_row['peso_piedras'], 'ea_pm': ea_row['peso_fraccion_mayor'], 'ea_p250': ea_row['peso_fraccion_250']})
        
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
        cur.execute('DELETE FROM ph_conductividad WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM materia_organica WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM estabilidad_agregados WHERE muestra_id = %s', (muestra_id,))
        cur.execute('DELETE FROM muestras WHERE id = %s AND usuario_id = %s', (muestra_id, session['usuario_id']))
        conexion.commit()
        flash('La muestra ha sido eliminada por completo.', 'success')
    finally: 
        cur.close()
        conexion.close()
    return redirect(url_for('inicio'))

@app.route('/descargar_csv')
def descargar_csv():
    if 'usuario_id' not in session: return redirect(url_for('login'))
    usuario_id = session['usuario_id']
    conexion = obtener_conexion()
    cur = conexion.cursor()
    
    consulta = '''SELECT m.id AS ID, m.nombre_muestra AS Muestra, m.cultivo AS Cultivo, m.textura AS Textura, m.latitud AS Latitud, m.longitud AS Longitud, m.descripcion AS Descripcion, 
                  c.resultado_carbono AS Carbono_Activo, p.ph AS pH, p.conductividad AS Conductividad, mo.resultado_porcentaje AS Mat_Particulada_Porc, 
                  ea.porcentaje_mayor_2mm AS Agregados_Mayor_2mm_Porc, ea.porcentaje_250_2mm AS Agregados_250_2mm_Porc 
                  FROM muestras m 
                  LEFT JOIN carbono_activo c ON m.id = c.muestra_id 
                  LEFT JOIN ph_conductividad p ON m.id = p.muestra_id 
                  LEFT JOIN materia_organica mo ON m.id = mo.muestra_id 
                  LEFT JOIN estabilidad_agregados ea ON m.id = ea.muestra_id 
                  WHERE m.usuario_id = %s'''
                  
    cur.execute(consulta, (usuario_id,))
    filas = cur.fetchall()
    
    # En Psycopg 3, cur.description es un poco diferente, obtenemos el nombre de la columna así:
    nombres_columnas = [col.name for col in cur.description]
    
    cur.close()
    conexion.close()
    
    output = io.StringIO()
    output.write('\ufeff') 
    writer = csv.writer(output, delimiter=';')
    writer.writerow(nombres_columnas)
    for fila in filas: writer.writerow(fila)
    
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=Mis_Datos_Suelos.csv"})

@app.route('/sincronizar_api', methods=['POST'])
def sincronizar_api():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    url_api = "https://app.surveystack.io/api/submissions/csv?survey=69a78356a519d930190644d0&expandAllMatrices=true"

    try:
        req = urllib.request.Request(url_api, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            lineas = response.read().decode('utf-8').splitlines()

        # Buscamos la fila de los datos reales (_id)
        indice_cabecera = 0
        for i, linea in enumerate(lineas):
            if '_id' in linea:
                indice_cabecera = i
                break
        
        contenido_util = io.StringIO("\n".join(lineas[indice_cabecera:]))
        lector = csv.DictReader(contenido_util, delimiter=',') 
        
        conexion = obtener_conexion()
        cur = conexion.cursor()
        usuario_actual = session['usuario_id']
        contador = 0
        
        for fila in lector:
            nombre, cultivo, textura, id_unico = None, None, None, None
            lat, lon, desc, info = None, None, None, None
            
            for col, valor in fila.items():
                if not col: continue
                c = col.lower().strip()
                if c == '_id' or c == 'id': id_unico = valor
                elif 'nombre_muestra' in c: nombre = valor
                elif 'cultivo' in c: cultivo = valor
                elif 'textura' in c: textura = valor
                elif 'latitud' in c: lat = valor
                elif 'longitud' in c: lon = valor
                elif 'descrip' in c: desc = valor
                elif 'info' in c: info = valor

            if not id_unico: continue 

            # Generamos el nombre con el ID para evitar que se pisen muestras distintas
            base_nombre = str(nombre).strip() if nombre and str(nombre).strip() != "" else "Muestra"
            nombre_final = f"{base_nombre} (#{str(id_unico)[-4:]})"

            # INSTRUCCIÓN MAESTRA: INSERT ON CONFLICT (UPSERT)
            # Esto intenta insertar, y si hay conflicto de nombre+usuario, actualiza.
            cur.execute('''
                INSERT INTO muestras (usuario_id, nombre_muestra, cultivo, textura, latitud, longitud, descripcion, informacion_relevante) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (usuario_id, nombre_muestra) 
                DO UPDATE SET 
                    cultivo = EXCLUDED.cultivo,
                    textura = EXCLUDED.textura,
                    latitud = EXCLUDED.latitud,
                    longitud = EXCLUDED.longitud,
                    descripcion = EXCLUDED.descripcion,
                    informacion_relevante = EXCLUDED.informacion_relevante
            ''', (usuario_actual, nombre_final, cultivo, textura, lat, lon, desc, info))
            
            contador += 1
                    
        conexion.commit()
        cur.close()
        conexion.close()
        
        flash(f'¡Sincronización exitosa! Se procesaron {contador} registros de SurveyStack.', 'success')
        
    except Exception as e:
        flash(f'Error en la base de datos: {str(e)}', 'danger')
        
    return redirect(url_for('inicio'))

if __name__ == '__main__':

    app.run(debug=True)




