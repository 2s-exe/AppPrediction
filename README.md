# RisqueAbi — Abidjan Sécurité (Python pur)

Application d'évaluation du risque d'agression à Abidjan.
**Aucun framework, aucune dépendance externe.**
Uniquement la bibliothèque standard Python.

## Stack technique

| Composant        | Technologie              |
|------------------|--------------------------|
| Serveur HTTP     | `http.server` (stdlib)   |
| Base de données  | `sqlite3` (stdlib)       |
| Parsing CSV      | `csv` (stdlib)           |
| JSON API         | `json` (stdlib)          |
| HTML             | f-strings Python         |
| Dépendances pip  | **aucune**               |

## Structure

```
risque_abidjan/
├── init_db.py                    ← Charge le CSV → SQLite
├── app.py                        ← Serveur HTTP + logique de risque
├── agressions_abidjan_clean.csv  ← Données sources
├── agressions.db                 ← Base SQLite (créée par init_db.py)
└── README.md
```

## Utilisation

### Étape 1 — Installer les riquirement
```bash
install r requirements.txt
```

### Étape 2 — Initialiser la base
```bash
python init_db.py
```
Lit le CSV et peuple `agressions.db` avec 6 tables SQLite.

### Étape 3 — Lancer le serveur
```bash
python app.py
```
Ouvrez **http://localhost:8000** dans votre navigateur.

## Endpoints

| URL            | Méthode | Description                     |
|----------------|---------|---------------------------------|
| `/`            | GET     | Interface utilisateur HTML      |
| `/api/risk`    | POST    | Calcul du score de risque       |
| `/api/stats`   | GET     | Toutes les statistiques (JSON)  |

### POST /api/risk
```json
{ "commune": "Abobo", "sex": "Femme", "age": "Adulte", "heure": "21:30" }
```
Réponse :
```json
{
  "score": 83,
  "level": "ÉLEVÉ",
  "color": "#e74c3c",
  "scores": { "commune": 100, "heure": 60, "sexe": 80, "age": 100 }
}
```

## Calcul du risque

Score pondéré 0–100 depuis la BD SQLite :

| Facteur  | Poids | Table SQLite      |
|----------|-------|-------------------|
| Commune  | 30 %  | `stats_commune`   |
| Horaire  | 30 %  | `stats_heure`     |
| Sexe     | 25 %  | `stats_sexe`      |
| Âge      | 15 %  | `stats_age`       |

- **< 40** → 🟢 Faible
- **40–65** → 🟠 Modéré  
- **> 65** → 🔴 Élevé
