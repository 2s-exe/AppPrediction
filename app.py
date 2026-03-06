"""
app.py — Serveur HTTP pur Python (http.server) + SQLite
Aucune dépendance externe — bibliothèque standard uniquement.

Lancement : python app.py
URL       : http://localhost:8000
"""

import sqlite3
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agressions.db")

# ─────────────────────────────────────────────────────────────────────────────
# Accès base de données
# ─────────────────────────────────────────────────────────────────────────────

def db_query(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_one(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Calcul du risque (toutes les valeurs viennent de la BD)
# ─────────────────────────────────────────────────────────────────────────────

def score_commune(commune):
    row = db_one("SELECT nb_incidents FROM stats_commune WHERE commune=?", (commune,))
    if not row:
        return 50
    max_v = db_one("SELECT MAX(nb_incidents) AS m FROM stats_commune")["m"] or 1
    return round(row["nb_incidents"] / max_v * 100)


def score_heure(heure_str):
    try:
        h = int(heure_str.split(":")[0])
    except (ValueError, AttributeError):
        return 50
    if   h >= 20 or h < 6:   tranche = "nuit"
    elif 6  <= h < 9:         tranche = "matin"
    elif 9  <= h < 17:        tranche = "journee"
    else:                      tranche = "soiree"
    row   = db_one("SELECT nb_incidents FROM stats_heure WHERE tranche=?", (tranche,))
    max_v = db_one("SELECT MAX(nb_incidents) AS m FROM stats_heure")["m"] or 1
    if not row:
        return 50
    base  = round(row["nb_incidents"] / max_v * 100)
    boost = {"nuit": 40, "soiree": 15, "matin": 5, "journee": 0}
    return min(100, base + boost.get(tranche, 0))


def score_sexe(sex):
    f = db_one("SELECT nb_incidents FROM stats_sexe WHERE sex='Femme'")
    m = db_one("SELECT nb_incidents FROM stats_sexe WHERE sex='Homme'")
    if not f or not m:
        return 60
    tot = f["nb_incidents"] + m["nb_incidents"]
    if sex == "Femme":
        return min(100, round(f["nb_incidents"] / tot * 100 + 25))
    if sex == "Homme":
        return min(100, round(m["nb_incidents"] / tot * 100 + 10))
    return 60


def score_age(categorie):
    row   = db_one("SELECT nb_incidents FROM stats_age WHERE categorie=?", (categorie,))
    max_v = db_one("SELECT MAX(nb_incidents) AS m FROM stats_age")["m"] or 1
    if not row:
        return 55
    base = round(row["nb_incidents"] / max_v * 100)
    vuln = {"Enfant": 20, "Adolescent": 15, "Adulte": 0}
    return min(100, base + vuln.get(categorie, 0))


def compute_risk(commune, sex, categorie, heure):
    weights = {r["facteur"]: r["poids"]
               for r in db_query("SELECT * FROM risk_weights")}
    scores = {
        "commune": score_commune(commune),
        "heure":   score_heure(heure),
        "sexe":    score_sexe(sex),
        "age":     score_age(categorie),
    }
    total = round(min(100, sum(weights.get(k, 0.25) * v for k, v in scores.items())))
    if   total < 40: level, color = "FAIBLE",  "#2ecc71"
    elif total < 65: level, color = "MODÉRÉ",  "#f39c12"
    else:            level, color = "ÉLEVÉ",   "#e74c3c"
    return {"score": total, "level": level, "color": color, "scores": scores}


# ─────────────────────────────────────────────────────────────────────────────
# Recommandations
# ─────────────────────────────────────────────────────────────────────────────

RECOS = {
    "FAIBLE": [
        {"icon": "✅", "text": "Restez vigilant·e même dans les zones et horaires à faible risque."},
        {"icon": "📱", "text": "Gardez votre téléphone chargé et partagez votre position avec un proche."},
        {"icon": "🚶", "text": "Privilégiez les rues animées et bien éclairées pour vos déplacements."},
        {"icon": "👀", "text": "Évitez les distractions (écouteurs, téléphone en main) dans la rue."},
    ],
    "MODÉRÉ": [
        {"icon": "⚠️", "text": "Évitez de vous déplacer seul·e dans des zones peu fréquentées."},
        {"icon": "🚕", "text": "Privilégiez les transports organisés (taxi, woro-woro de confiance)."},
        {"icon": "🤝", "text": "Déplacez-vous en groupe, surtout en soirée."},
        {"icon": "🌙", "text": "Limitez vos sorties nocturnes dans les zones à risque."},
        {"icon": "💼", "text": "Évitez d'afficher des objets de valeur (bijoux, téléphone, sac de marque)."},
    ],
    "ÉLEVÉ": [
        {"icon": "🚨", "text": "Risque élevé : limitez vos déplacements au strict nécessaire."},
        {"icon": "📞", "text": "Informez toujours un proche de votre destination et heure de retour."},
        {"icon": "🚗", "text": "Utilisez uniquement des véhicules de confiance — évitez les trajets à pied la nuit."},
        {"icon": "🌙", "text": "Évitez impérativement tout déplacement nocturne dans cette commune."},
        {"icon": "🔔", "text": "Mémorisez les numéros d'urgence : Police 110 / Gendarmerie 111."},
        {"icon": "👥", "text": "Ne vous déplacez jamais seul·e — accompagnez-vous de personnes de confiance."},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Génération du HTML (sans Jinja, concaténation Python pure)
# ─────────────────────────────────────────────────────────────────────────────

def build_commune_bars(communes):
    if not communes:
        return ""
    max_inc = communes[0]["nb_incidents"]
    html = ""
    for row in communes:
        pct = int(row["nb_incidents"] / max_inc * 100)
        c   = row["commune"]
        html += f"""
        <div class="bitem">
          <div class="bname" id="bname-{c}">{c}</div>
          <div class="btrack">
            <div class="bfill" id="bfill-{c}"
              style="width:{pct}%;background:linear-gradient(90deg,#2a2e3a,#353a4a)">
            </div>
          </div>
          <div class="bcnt">{row['nb_incidents']} cas</div>
        </div>"""
    return html


def build_html():
    communes = db_query(
        "SELECT commune, nb_incidents FROM stats_commune ORDER BY nb_incidents DESC")
    total    = db_one("SELECT COUNT(*) AS n FROM incidents")["n"]
    commune_bars = build_commune_bars(communes)
    recos_json   = json.dumps(RECOS, ensure_ascii=False)

    commune_options = "\n".join(
        f'<option value="{r["commune"]}">'
        f'{r["commune"]} — {r["nb_incidents"]} incidents</option>'
        for r in communes
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RisqueAbi — Abidjan Sécurité</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0a0c10;--surface:#12151c;--surface2:#1a1e28;
  --border:#252a38;--accent:#f0b429;--accent2:#e05c2a;
  --text:#e8eaf0;--muted:#6b7280;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh}}
body::before{{content:'';position:fixed;inset:0;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 512 512' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");
  pointer-events:none;z-index:9999;opacity:.4}}

header{{padding:1.5rem 2rem;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:1rem}}
.logo{{width:40px;height:40px;background:var(--accent);border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:'Syne',sans-serif;font-weight:800;font-size:1.2rem;color:#000;flex-shrink:0}}
.htext h1{{font-family:'Syne',sans-serif;font-size:1rem;font-weight:700}}
.htext p{{font-size:.72rem;color:var(--muted)}}
.dbadge{{margin-left:auto;background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:.3rem .9rem;font-size:.72rem;color:var(--muted)}}
.dbadge span{{color:var(--accent);font-weight:600}}

.main{{max-width:1000px;margin:0 auto;padding:2rem 1.5rem 4rem}}
.hero{{text-align:center;padding:2rem 0 1.5rem}}
.hero h2{{font-family:'Syne',sans-serif;font-size:clamp(1.5rem,4vw,2.4rem);font-weight:800;line-height:1.15;letter-spacing:-.02em}}
.hero h2 em{{font-style:normal;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hero p{{margin-top:.7rem;color:var(--muted);font-size:.85rem;max-width:480px;margin-inline:auto}}

.grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.4rem;margin-top:1.5rem}}
@media(max-width:640px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:1.4rem}}
.ctitle{{font-family:'Syne',sans-serif;font-size:.75rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:1.1rem;display:flex;align-items:center;gap:.5rem}}
.ctitle::before{{content:'';display:block;width:7px;height:7px;background:var(--accent);border-radius:50%}}

.field{{margin-bottom:1rem}}
label{{display:block;font-size:.78rem;font-weight:500;color:var(--muted);margin-bottom:.45rem;letter-spacing:.03em}}
select,input[type=time]{{width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:.7rem .95rem;font-size:.88rem;font-family:'DM Sans',sans-serif;appearance:none;outline:none;transition:border-color .2s;cursor:pointer}}
select:focus,input[type=time]:focus{{border-color:var(--accent);box-shadow:0 0 0 3px rgba(240,180,41,.1)}}
select option{{background:#1a1e28}}
.btn{{width:100%;padding:.85rem;background:var(--accent);color:#000;border:none;border-radius:12px;font-family:'Syne',sans-serif;font-size:.95rem;font-weight:700;letter-spacing:.03em;cursor:pointer;transition:transform .15s,box-shadow .15s;margin-top:.4rem}}
.btn:hover{{transform:translateY(-2px);box-shadow:0 8px 24px rgba(240,180,41,.3)}}
.btn:active{{transform:translateY(0)}}
.btn:disabled{{opacity:.5;cursor:not-allowed;transform:none}}

.risk-meter{{display:flex;flex-direction:column;align-items:center;gap:1.2rem}}
.gauge-wrap{{position:relative;width:170px;height:170px}}
.gauge-wrap svg{{transform:rotate(-90deg)}}
.gauge-bg{{fill:none;stroke:var(--border);stroke-width:12}}
.gauge-fill{{fill:none;stroke-width:12;stroke-linecap:round;transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1),stroke .4s}}
.gauge-center{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.gauge-pct{{font-family:'Syne',sans-serif;font-size:2rem;font-weight:800;line-height:1}}
.gauge-lbl{{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-top:.15rem}}
.rbadge{{display:inline-flex;align-items:center;gap:.5rem;padding:.45rem 1.1rem;border-radius:30px;font-family:'Syne',sans-serif;font-size:.8rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase}}
.rdot{{width:8px;height:8px;border-radius:50%}}

.frow{{display:flex;align-items:center;gap:.7rem;margin-bottom:.7rem}}
.fname{{font-size:.75rem;color:var(--muted);width:110px;flex-shrink:0}}
.ftrack{{flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden}}
.fbar{{height:100%;border-radius:3px;background:var(--accent);transition:width 1s cubic-bezier(.4,0,.2,1)}}
.fval{{font-size:.7rem;font-weight:500;width:34px;text-align:right}}

.bitem{{display:flex;align-items:center;gap:.7rem;margin-bottom:.65rem}}
.bname{{font-size:.75rem;color:var(--muted);width:85px;flex-shrink:0}}
.btrack{{flex:1;height:18px;background:var(--surface2);border-radius:4px;overflow:hidden}}
.bfill{{height:100%;border-radius:4px;transition:width 1s cubic-bezier(.4,0,.2,1)}}
.bfill.you{{outline:2px solid var(--accent)}}
.bcnt{{font-size:.72rem;color:var(--muted);width:55px;text-align:right}}
.youtag{{font-size:.6rem;font-weight:700;background:var(--accent);color:#000;border-radius:3px;padding:.1rem .3rem;margin-left:.3rem;vertical-align:middle}}

.rlist{{list-style:none}}
.rlist li{{display:flex;align-items:flex-start;gap:.75rem;padding:.7rem 0;border-bottom:1px solid var(--border);font-size:.82rem;line-height:1.5}}
.rlist li:last-child{{border-bottom:none}}
.rico{{width:28px;height:28px;flex-shrink:0;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:.85rem}}

.placeholder{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:210px;gap:.8rem}}
.placeholder .icon{{width:60px;height:60px;border-radius:50%;border:2px dashed var(--border);display:flex;align-items:center;justify-content:center;font-size:1.6rem}}
.placeholder p{{color:var(--muted);font-size:.82rem;text-align:center;line-height:1.5}}
.divider{{height:1px;background:var(--border);margin:.4rem 0 1rem}}
.srcnote{{text-align:center;margin-top:2rem;font-size:.72rem;color:var(--muted)}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:translateY(0)}}}}
.animate{{animation:fadeUp .5s ease both}}
</style>
</head>
<body>

<header>
  <div class="logo">⚠</div>
  <div class="htext">
    <h1>RisqueAbi — Abidjan Sécurité</h1>
    <p>Python pur · http.server · SQLite · Aucun framework</p>
  </div>
  <div class="dbadge">Base : <span>{total}</span> incidents</div>
</header>

<div class="main">
  <div class="hero">
    <h2>Évaluez votre <em>risque d'agression</em><br>à Abidjan</h2>
    <p>Renseignez votre profil et situation. Score calculé à partir de <strong style="color:var(--accent)">{total} incidents réels</strong> stockés dans SQLite.</p>
  </div>

  <div class="grid">

    <!-- Formulaire -->
    <div class="card animate">
      <div class="ctitle">Votre profil</div>
      <div class="field">
        <label>Sexe</label>
        <select id="sex">
          <option value="">— Sélectionner —</option>
          <option value="Femme">Femme</option>
          <option value="Homme">Homme</option>
        </select>
      </div>
      <div class="field">
        <label>Catégorie d'âge</label>
        <select id="age">
          <option value="">— Sélectionner —</option>
          <option value="Enfant">Enfant (moins de 12 ans)</option>
          <option value="Adolescent">Adolescent (12–17 ans)</option>
          <option value="Adulte">Adulte (18 ans et plus)</option>
        </select>
      </div>
      <div class="field">
        <label>Commune</label>
        <select id="commune">
          <option value="">— Sélectionner —</option>
          {commune_options}
        </select>
      </div>
      <div class="field">
        <label>Heure de déplacement</label>
        <input type="time" id="heure" value="12:00">
      </div>
      <button class="btn" id="btn" onclick="analyser()">Analyser mon risque →</button>
    </div>

    <!-- Résultat -->
    <div class="card animate" id="result-card">
      <div class="ctitle">Niveau de risque</div>
      <div id="result-placeholder" class="placeholder">
        <div class="icon">📊</div>
        <p>Remplissez le formulaire<br>pour voir votre analyse</p>
      </div>
      <div id="result-content" style="display:none">
        <div class="risk-meter">
          <div class="gauge-wrap">
            <svg width="170" height="170" viewBox="0 0 170 170">
              <circle class="gauge-bg" cx="85" cy="85" r="70"/>
              <circle class="gauge-fill" id="gauge-fill" cx="85" cy="85" r="70"
                stroke-dasharray="439.82" stroke-dashoffset="439.82"/>
            </svg>
            <div class="gauge-center">
              <div class="gauge-pct" id="gauge-pct">0%</div>
              <div class="gauge-lbl">Risque</div>
            </div>
          </div>
          <div class="rbadge" id="rbadge">
            <div class="rdot" id="rdot"></div>
            <span id="rlabel">–</span>
          </div>
          <div style="width:100%">
            <div class="divider"></div>
            <div id="factors"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Graphique communes -->
    <div class="card animate">
      <div class="ctitle">Incidents par commune</div>
      <div id="commune-chart">{commune_bars}</div>
    </div>

    <!-- Recommandations -->
    <div class="card animate" id="reco-card" style="display:none">
      <div class="ctitle">Recommandations</div>
      <ul class="rlist" id="reco-list"></ul>
    </div>

  </div>

  <p class="srcnote">
    Source : <code>agressions_abidjan_clean.csv</code> →
    <code>agressions.db</code> (SQLite) ·
    Pondération : commune 30% · heure 30% · sexe 25% · âge 15% ·
    Serveur : <code>http.server</code> Python pur
  </p>
</div>

<script>
const RECOS = {recos_json};
const CIRC  = 439.82;

async function analyser() {{
  const commune = document.getElementById('commune').value;
  const sex     = document.getElementById('sex').value;
  const age     = document.getElementById('age').value;
  const heure   = document.getElementById('heure').value || '12:00';

  if (!commune || !sex || !age) {{
    alert('Veuillez renseigner tous les champs.');
    return;
  }}

  const btn = document.getElementById('btn');
  btn.disabled = true;
  btn.textContent = 'Calcul en cours…';

  const res  = await fetch('/api/risk', {{
    method:  'POST',
    headers: {{'Content-Type': 'application/json'}},
    body:    JSON.stringify({{commune, sex, age, heure}})
  }});
  const data = await res.json();
  btn.disabled = false;
  btn.textContent = 'Analyser mon risque →';
  afficherResultat(data, commune);
}}

function afficherResultat(data, commune) {{
  document.getElementById('result-placeholder').style.display = 'none';
  const content = document.getElementById('result-content');
  content.style.display = 'block';
  content.style.animation = 'none';
  void content.offsetWidth;
  content.style.animation = 'fadeUp .5s ease both';

  // Jauge
  const fill = document.getElementById('gauge-fill');
  fill.style.stroke = data.color;
  fill.style.strokeDashoffset = CIRC;
  setTimeout(() => {{
    fill.style.strokeDashoffset = CIRC - (data.score / 100) * CIRC;
  }}, 50);

  // Compteur animé
  const pctEl = document.getElementById('gauge-pct');
  pctEl.style.color = data.color;
  let c = 0;
  const step = Math.ceil(data.score / 40);
  const timer = setInterval(() => {{
    c = Math.min(c + step, data.score);
    pctEl.textContent = c + '%';
    if (c >= data.score) clearInterval(timer);
  }}, 25);

  // Badge niveau
  const badge = document.getElementById('rbadge');
  document.getElementById('rdot').style.background = data.color;
  document.getElementById('rlabel').textContent    = 'RISQUE ' + data.level;
  badge.style.cssText = `background:${{data.color}}22;border:1px solid ${{data.color}}55;color:${{data.color}}`;

  // Barres de facteurs
  const labels = {{commune:'Commune',heure:'Horaire',sexe:'Sexe',age:'Âge'}};
  const fEl = document.getElementById('factors');
  fEl.innerHTML = '';
  for (const [k, v] of Object.entries(data.scores)) {{
    const fc = v >= 70 ? '#e74c3c' : v >= 45 ? '#f39c12' : '#2ecc71';
    fEl.innerHTML += `
      <div class="frow">
        <div class="fname">${{labels[k]}}</div>
        <div class="ftrack">
          <div class="fbar" style="width:0%;background:${{fc}}" data-w="${{v}}"></div>
        </div>
        <div class="fval" style="color:${{fc}}">${{v}}%</div>
      </div>`;
  }}
  setTimeout(() => {{
    document.querySelectorAll('.fbar').forEach(b => b.style.width = b.dataset.w + '%');
  }}, 80);

  // Surligné commune sélectionnée dans le graphique
  document.querySelectorAll('.bfill').forEach(b => {{
    b.style.background = 'linear-gradient(90deg,#2a2e3a,#353a4a)';
    b.classList.remove('you');
  }});
  document.querySelectorAll('.bname').forEach(n => {{
    const t = n.querySelector('.youtag');
    if (t) t.remove();
  }});
  const bf = document.getElementById('bfill-' + commune);
  const bn = document.getElementById('bname-' + commune);
  if (bf) {{ bf.style.background = 'linear-gradient(90deg,var(--accent2),var(--accent))'; bf.classList.add('you'); }}
  if (bn) {{ bn.innerHTML += '<span class="youtag">VOUS</span>'; }}

  // Recommandations
  const recoCard = document.getElementById('reco-card');
  recoCard.style.display = 'block';
  recoCard.style.animation = 'none';
  void recoCard.offsetWidth;
  recoCard.style.animation = 'fadeUp .5s ease both';
  const bgColor = {{FAIBLE:'#1a3a2a',MODÉRÉ:'#3a2d1a',ÉLEVÉ:'#3a1a1a'}};
  document.getElementById('reco-list').innerHTML =
    (RECOS[data.level] || []).map(r =>
      `<li>
         <div class="rico" style="background:${{bgColor[data.level]}}">${{r.icon}}</div>
         <span>${{r.text}}</span>
       </li>`
    ).join('');
}}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Gestionnaire de requêtes HTTP (pur http.server)
# ─────────────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    # ── silence les logs d'accès dans le terminal ─────────────────────────
    def log_message(self, fmt, *args):
        print(f"  [{self.command}] {self.path}  →  {args[1]}")

    # ── GET ───────────────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            html = build_html().encode("utf-8")
            self._send(200, "text/html; charset=utf-8", html)

        elif path == "/api/stats":
            payload = {
                "total":    db_one("SELECT COUNT(*) AS n FROM incidents")["n"],
                "communes": db_query("SELECT * FROM stats_commune ORDER BY nb_incidents DESC"),
                "heures":   db_query("SELECT * FROM stats_heure ORDER BY nb_incidents DESC"),
                "sexes":    db_query("SELECT * FROM stats_sexe ORDER BY nb_incidents DESC"),
                "ages":     db_query("SELECT * FROM stats_age ORDER BY nb_incidents DESC"),
                "weights":  db_query("SELECT * FROM risk_weights"),
            }
            self._json(200, payload)

        else:
            self._send(404, "text/plain", b"404 Not Found")

    # ── POST ──────────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/risk":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                data   = json.loads(body)
                result = compute_risk(
                    commune  = data.get("commune", ""),
                    sex      = data.get("sex", ""),
                    categorie= data.get("age", ""),
                    heure    = data.get("heure", "12:00"),
                )
                self._json(200, result)
            except Exception as e:
                self._json(400, {"error": str(e)})
        else:
            self._send(404, "text/plain", b"404 Not Found")

    # ── helpers ───────────────────────────────────────────────────────────
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, "application/json; charset=utf-8", body)


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PORT = 8000
    sep  = "=" * 52

    if not os.path.exists(DB_PATH):
        print(f"\n⚠  Base introuvable : {DB_PATH}")
        print("   Lancez d'abord : python init_db.py\n")
        raise SystemExit(1)

    print(f"\n{sep}")
    print("  RisqueAbi — Abidjan Sécurité")
    print(f"  Python pur · http.server · SQLite")
    print(sep)
    print(f"  DB   : {DB_PATH}")
    print(f"  URL  : http://localhost:{PORT}")
    print(f"  Stats: http://localhost:{PORT}/api/stats")
    print(f"{sep}")
    print("  Ctrl+C pour arrêter\n")

    server = HTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Serveur arrêté.")
        server.server_close()
