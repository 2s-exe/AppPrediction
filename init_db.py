"""
init_db.py — Charge agressions_abidjan_clean.csv dans SQLite
Aucune dépendance externe — bibliothèque standard Python uniquement.
"""

import sqlite3
import csv
import os

CSV_PATH = os.path.join(os.path.dirname(__file__), "agressions_abidjan_clean.csv")
DB_PATH  = os.path.join(os.path.dirname(__file__), "agressions.db")


def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS incidents (
            id        INTEGER PRIMARY KEY,
            heure     TEXT,
            commune   TEXT,
            sex       TEXT,
            categorie TEXT
        );

        CREATE TABLE IF NOT EXISTS stats_commune (
            commune      TEXT PRIMARY KEY,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        CREATE TABLE IF NOT EXISTS stats_heure (
            tranche      TEXT PRIMARY KEY,
            label        TEXT,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        CREATE TABLE IF NOT EXISTS stats_sexe (
            sex          TEXT PRIMARY KEY,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        CREATE TABLE IF NOT EXISTS stats_age (
            categorie    TEXT PRIMARY KEY,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        CREATE TABLE IF NOT EXISTS risk_weights (
            facteur TEXT PRIMARY KEY,
            poids   REAL
        );
    """)
    conn.commit()


def classify_hour(heure_str):
    if not heure_str or heure_str.strip().lower() in ("non précisée", ""):
        return None
    try:
        h = int(heure_str.strip().split(":")[0])
    except ValueError:
        return None
    if h >= 20 or h < 6:
        return "nuit"
    if 6 <= h < 9:
        return "matin"
    if 9 <= h < 17:
        return "journee"
    return "soiree"


def load_csv(conn):
    conn.execute("DELETE FROM incidents")
    count = 0
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute(
                "INSERT INTO incidents VALUES (?,?,?,?,?)",
                (int(row["id"]), row["heure"].strip(),
                 row["commune"].strip(), row["sex"].strip(),
                 row["categorie"].strip())
            )
            count += 1
    conn.commit()
    print(f"  ✔  {count} incidents insérés")
    return count


def build_stats(conn, total):
    # Communes
    conn.execute("DELETE FROM stats_commune")
    conn.executescript("""
        INSERT INTO stats_commune
        SELECT commune, COUNT(*) AS nb,
               ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM incidents),2)
        FROM incidents
        WHERE commune != '' AND commune != 'Non précisée'
        GROUP BY commune ORDER BY nb DESC;
    """)

    # Tranches horaires
    conn.execute("DELETE FROM stats_heure")
    labels  = {"nuit":"Nuit (20h–6h)","matin":"Matin (6h–9h)",
               "journee":"Journée (9h–17h)","soiree":"Soirée (17h–20h)"}
    tranches = {k: 0 for k in labels}
    for (h,) in conn.execute("SELECT heure FROM incidents"):
        t = classify_hour(h)
        if t:
            tranches[t] += 1
    for t, nb in tranches.items():
        conn.execute("INSERT OR REPLACE INTO stats_heure VALUES (?,?,?,?)",
                     (t, labels[t], nb, round(nb*100.0/total, 2)))

    # Sexe
    conn.execute("DELETE FROM stats_sexe")
    conn.executescript("""
        INSERT INTO stats_sexe
        SELECT sex, COUNT(*), ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM incidents),2)
        FROM incidents WHERE sex NOT IN ('Non précisé','') GROUP BY sex;
    """)

    # Age
    conn.execute("DELETE FROM stats_age")
    conn.executescript("""
        INSERT INTO stats_age
        SELECT categorie, COUNT(*), ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM incidents),2)
        FROM incidents WHERE categorie NOT IN ('Non précisé','') GROUP BY categorie;
    """)

    conn.commit()
    print("  ✔  Tables de statistiques construites")


def set_weights(conn):
    conn.execute("DELETE FROM risk_weights")
    conn.executemany("INSERT INTO risk_weights VALUES (?,?)",
                     [("commune",0.30),("heure",0.30),("sexe",0.25),("age",0.15)])
    conn.commit()
    print("  ✔  Poids de risque enregistrés")


def main():
    sep = "=" * 52
    print(f"\n{sep}")
    print("  Init base SQLite — Abidjan Sécurité")
    print(sep)
    print(f"  CSV : {CSV_PATH}")
    print(f"  DB  : {DB_PATH}\n")
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    total = load_csv(conn)
    build_stats(conn, total)
    set_weights(conn)
    conn.close()
    print(f"\n  Base prête → {DB_PATH}")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
