#!/usr/bin/env python3
"""Junta várias fontes EPG (XMLTV) num único guide.xml.gz.

- Fonte fora do ar ou quebrada é pulada (não derruba o resto).
- Canal repetido: fica o canal da primeira fonte que tiver.
- Programação repetida: fica a fonte que cobre mais horas pra frente.
- Se existir playlist.m3u (ou M3U_URL), mantém só os canais usados nela.
"""
import gzip
import lzma
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# Ordem = prioridade. Comente/descomente à vontade.
SOURCES = [
    ("EPGTV", "https://raw.githubusercontent.com/rootcoder/epgtv/main/guide.xml.gz"),
    ("epgshare BR2", "https://epgshare01.online/epgshare01/epg_ripper_BR2.xml.gz"),
    ("epgshare PT1", "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz"),
    ("RadarTV", "https://althierestm.github.io/Lista-RadarTV/epg.xml"),
    ("PlutoTV", "https://raw.githubusercontent.com/matthuisman/i.mjh.nz/refs/heads/master/PlutoTV/br.xml"),
    ("Canais Esporte", "https://raw.githubusercontent.com/LITUATUI/M3UPT/refs/heads/main/EPG/epg-rytec-pt.xml.xz"),
    # EPGONTVHDBR (http://epgontvhdbr.com/) é só a página inicial; cole aqui o link direto do .xml/.xml.gz se tiver.
]

M3U_URL = os.environ.get("M3U_URL", "")      # opcional: link da sua playlist
M3U_FILE = os.environ.get("M3U_FILE", "playlist.m3u")  # ou arquivo no repo
OUT = os.environ.get("OUT", "guide.xml.gz")
KEEP_PAST_HOURS = 6                          # descarta programa que acabou há mais que isso


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (epg-merge)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    elif data[:6] == b"\xfd7zXZ\x00":
        data = lzma.decompress(data)
    return data


def parse_time(s):
    s = s.strip()
    dt = datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    tz = timezone.utc
    m = re.search(r"([+-])(\d{2})(\d{2})$", s)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        tz = timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    return dt.replace(tzinfo=tz)


def wanted_ids():
    text = ""
    try:
        if M3U_URL:
            text = fetch(M3U_URL).decode("utf-8", "ignore")
        elif os.path.exists(M3U_FILE):
            text = open(M3U_FILE, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        print(f"[aviso] não consegui ler a playlist: {e}")
    ids = {i.strip().lower() for i in re.findall(r'tvg-id="([^"]+)"', text) if i.strip()}
    return ids


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=KEEP_PAST_HOURS)
    channels = {}   # id -> <channel>
    progs = {}      # id -> (fim_da_cobertura, [<programme>...], fonte)

    for name, url in SOURCES:
        try:
            root = ET.fromstring(fetch(url))
        except Exception as e:
            print(f"[FALHOU] {name}: {e}")
            continue

        for ch in root.findall("channel"):
            cid = ch.get("id")
            if cid and cid not in channels:
                channels[cid] = ch

        by_ch = {}
        for p in root.findall("programme"):
            try:
                stop = parse_time(p.get("stop") or p.get("start"))
            except Exception:
                continue
            if stop < cutoff:
                continue
            by_ch.setdefault(p.get("channel"), []).append((stop, p))

        used = 0
        for cid, lst in by_ch.items():
            end = max(s for s, _ in lst)
            cur = progs.get(cid)
            if cur is None or end > cur[0] + timedelta(hours=1):
                progs[cid] = (end, [p for _, p in lst], name)
                used += 1
        print(f"[ok] {name}: {len(by_ch)} canais com programação, {used} usados")

    ids = wanted_ids()
    if ids:
        keep = {c for c in set(channels) | set(progs) if c.lower() in ids}
        have = {c.lower() for c in keep}
        print(f"[playlist] {len(ids)} tvg-id na playlist, {len(have)} com EPG")
        miss = sorted(ids - have)
        if miss:
            print(f"[playlist] sem EPG em nenhuma fonte ({len(miss)}): {', '.join(miss[:30])}"
                  + (" ..." if len(miss) > 30 else ""))
    else:
        keep = set(channels) | set(progs)

    tv = ET.Element("tv", {"generator-info-name": "epg-merge"})
    for cid in sorted(keep):
        if cid in channels:
            tv.append(channels[cid])
    total = 0
    for cid in sorted(keep):
        if cid in progs:
            for p in sorted(progs[cid][1], key=lambda x: x.get("start")):
                tv.append(p)
                total += 1

    with gzip.open(OUT, "wb") as f:
        ET.ElementTree(tv).write(f, encoding="utf-8", xml_declaration=True)
    print(f"[pronto] {OUT}: {len(keep)} canais, {total} programas")
    if total == 0:
        sys.exit("nenhuma programação coletada")


if __name__ == "__main__":
    main()
