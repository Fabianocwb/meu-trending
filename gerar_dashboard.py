"""
Dashboard de projetos em alta no GitHub.

O que este script faz:
  1. Lê a página oficial "Trending" do GitHub (semanal) para cada linguagem
     configurada, que traz quantas estrelas cada projeto ganhou NA SEMANA.
  2. Usa a API de busca do GitHub para achar projetos NOVOS (criados nos
     últimos 7 dias) com mais estrelas em cada tema configurado.
  3. Gera o README.md (o "dashboard") e salva um histórico em JSON.

Para personalizar, altere só a seção CONFIGURAÇÃO abaixo.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

# ============================== CONFIGURAÇÃO ==============================

# Linguagens da página Trending ("" = todas as linguagens).
# Delphi aparece no GitHub como "pascal".
LINGUAGENS = {
    "": "🌍 Geral (todas as linguagens)",
    "python": "🐍 Python",
    "tsql": "🗄️ T-SQL / SQL Server",
    "pascal": "🏛️ Delphi / Pascal",
    "powershell": "⚡ PowerShell",
}

# Temas (topics do GitHub) para buscar projetos novos da semana.
TEMAS = {
    "reverse-engineering": "🔍 Engenharia reversa",
    "llm": "🤖 LLMs / IA",
    "ollama": "🦙 IA local (Ollama)",
    "sql-server": "🗄️ SQL Server",
    "automation": "⚙️ Automação",
}

QTD_TRENDING = 10   # projetos por linguagem
QTD_TEMA = 5        # projetos por tema
PERIODO = "weekly"  # "daily", "weekly" ou "monthly"

# ==========================================================================

FUSO_BR = timezone(timedelta(hours=-3))
CABECALHOS = {"User-Agent": "dashboard-trending-script"}
TOKEN = os.environ.get("GITHUB_TOKEN")  # o Actions fornece automaticamente


def limpar(texto: str, limite: int = 120) -> str:
    """Deixa a descrição segura para tabela Markdown."""
    texto = re.sub(r"\s+", " ", texto or "").strip().replace("|", "/")
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def fmt(n: int) -> str:
    """Formata número no padrão brasileiro: 12345 -> 12.345"""
    return f"{n:,}".replace(",", ".")


def numero(texto: str) -> int:
    digitos = re.sub(r"[^\d]", "", texto or "")
    return int(digitos) if digitos else 0


def buscar_trending(linguagem: str) -> list[dict]:
    caminho = f"/{linguagem}" if linguagem else ""
    url = f"https://github.com/trending{caminho}?since={PERIODO}"
    resp = requests.get(url, headers=CABECALHOS, timeout=30)
    resp.raise_for_status()
    sopa = BeautifulSoup(resp.text, "html.parser")

    projetos = []
    for item in sopa.select("article.Box-row")[:QTD_TRENDING]:
        link = item.select_one("h2 a")
        if not link:
            continue
        nome = re.sub(r"\s+", "", link.get_text())
        desc = item.select_one("p")
        ling = item.select_one('[itemprop="programmingLanguage"]')
        total = item.select_one('a[href$="/stargazers"]')
        periodo = item.select_one("span.float-sm-right")
        projetos.append({
            "nome": nome,
            "url": f"https://github.com/{nome}",
            "descricao": limpar(desc.get_text() if desc else ""),
            "linguagem": ling.get_text(strip=True) if ling else "",
            "estrelas_total": numero(total.get_text() if total else ""),
            "estrelas_periodo": numero(periodo.get_text() if periodo else ""),
        })
    return projetos


def buscar_tema(tema: str) -> list[dict]:
    desde = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    cab = dict(CABECALHOS, Accept="application/vnd.github+json")
    if TOKEN:
        cab["Authorization"] = f"Bearer {TOKEN}"
    resp = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": f"topic:{tema} created:>{desde}", "sort": "stars",
                "order": "desc", "per_page": QTD_TEMA},
        headers=cab, timeout=30,
    )
    resp.raise_for_status()
    return [{
        "nome": r["full_name"],
        "url": r["html_url"],
        "descricao": limpar(r.get("description") or ""),
        "linguagem": r.get("language") or "",
        "estrelas_total": r["stargazers_count"],
    } for r in resp.json().get("items", [])]


def tabela_trending(projetos: list[dict]) -> str:
    if not projetos:
        return "_Nenhum projeto em alta encontrado neste período._\n"
    linhas = ["| # | Projeto | ⭐ na semana | ⭐ total | Linguagem | Descrição |",
              "|---|---|---:|---:|---|---|"]
    for i, p in enumerate(projetos, 1):
        linhas.append(f"| {i} | [{p['nome']}]({p['url']}) | +{fmt(p['estrelas_periodo'])} "
                      f"| {fmt(p['estrelas_total'])} | {p['linguagem']} | {p['descricao']} |")
    return "\n".join(linhas) + "\n"


def tabela_tema(projetos: list[dict]) -> str:
    if not projetos:
        return "_Nenhum projeto novo neste tema na última semana._\n"
    linhas = ["| # | Projeto | ⭐ | Linguagem | Descrição |", "|---|---|---:|---|---|"]
    for i, p in enumerate(projetos, 1):
        linhas.append(f"| {i} | [{p['nome']}]({p['url']}) | {fmt(p['estrelas_total'])} "
                      f"| {p['linguagem']} | {p['descricao']} |")
    return "\n".join(linhas) + "\n"


def ancora(titulo: str) -> str:
    """Gera o link interno (âncora) que o GitHub cria para cada título."""
    t = titulo.lower()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    return t.strip().replace(" ", "-")


def main() -> int:
    agora = datetime.now(FUSO_BR)
    dados = {"gerado_em": agora.isoformat(), "trending": {}, "temas": {}}
    erros = []

    for ling, titulo in LINGUAGENS.items():
        try:
            dados["trending"][titulo] = buscar_trending(ling)
            print(f"[OK] Trending {titulo}: {len(dados['trending'][titulo])} projetos")
        except Exception as e:  # noqa: BLE001
            erros.append(f"Trending {titulo}: {e}")
            dados["trending"][titulo] = []

    for tema, titulo in TEMAS.items():
        try:
            dados["temas"][titulo] = buscar_tema(tema)
            print(f"[OK] Tema {titulo}: {len(dados['temas'][titulo])} projetos")
        except Exception as e:  # noqa: BLE001
            erros.append(f"Tema {titulo}: {e}")
            dados["temas"][titulo] = []

    # ---------- monta o README ----------
    md = [
        "# 📈 Meu Trending do GitHub\n",
        f"> Atualizado automaticamente em **{agora:%d/%m/%Y às %H:%M}** (horário de Brasília).  ",
        "> Fonte: [GitHub Trending](https://github.com/trending?since=weekly) "
        "e API de busca do GitHub.\n",
        "## Sumário\n",
        "**Em alta na semana:** " + " · ".join(
            f"[{t}](#{ancora(t)})" for t in LINGUAGENS.values()) + "  ",
        "**Novidades por tema:** " + " · ".join(
            f"[{t}](#{ancora(t)})" for t in TEMAS.values()) + "\n",
        "---\n",
        "# 🔥 Em alta na semana\n",
        "_Projetos que mais ganharam estrelas nos últimos 7 dias._\n",
    ]
    for titulo, projetos in dados["trending"].items():
        md += [f"## {titulo}\n", tabela_trending(projetos)]

    md += ["---\n", "# 🆕 Projetos novos da semana por tema\n",
           "_Repositórios criados nos últimos 7 dias, ordenados por estrelas._\n"]
    for titulo, projetos in dados["temas"].items():
        md += [f"## {titulo}\n", tabela_tema(projetos)]

    if erros:
        md += ["---\n", "<details><summary>⚠️ Avisos desta execução</summary>\n",
               "\n".join(f"- {e}" for e in erros), "\n</details>\n"]

    md.append("\n---\n_Gerado por `gerar_dashboard.py` via GitHub Actions._\n")

    with open("README.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    os.makedirs("historico", exist_ok=True)
    with open(f"historico/{agora:%Y-%m-%d}.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in dados["trending"].values()) + \
        sum(len(v) for v in dados["temas"].values())
    print(f"\nResumo: {total} projetos coletados, {len(erros)} erro(s).")
    print("README.md e historico/ atualizados.")
    # Só falha se NADA foi coletado (assim o Actions avisa você por e-mail)
    return 1 if total == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
