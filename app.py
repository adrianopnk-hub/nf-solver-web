# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, Response, jsonify
import re
from typing import List, Tuple, Optional

app = Flask(__name__)

# ----------------------------
# Utils: parse/format
# ----------------------------

def parse_number_br_or_en(s: str) -> Optional[int]:
    """
    Converte string de dinheiro para CENTAVOS (int).
    Aceita: 1.234,56 | 1,234.56 | 1234,56 | 1234.56 | 1234 | -10,00 | -10.00
    Retorna None se não conseguir converter.
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    s = s.replace(" ", "")

    # aceita sinal
    sign = 1
    if s.startswith('+'):
        s = s[1:]
    elif s.startswith('-'):
        s = s[1:]
        sign = -1

    if "," in s and "." in s:
        # Decide pelo último separador como decimal
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_comma > last_dot:
            s_norm = s.replace(".", "").replace(",", ".")
        else:
            s_norm = s.replace(",", "")
    elif "," in s:
        if re.match(r".*,\d{2}$", s):
            s_norm = s.replace(".", "").replace(",", ".")
        else:
            s_norm = s.replace(",", "")
    else:
        s_norm = s

    try:
        valor = float(s_norm) * sign
        return int(round(valor * 100))
    except Exception:
        return None


def parse_linhas_para_centavos(texto: str) -> List[Tuple[str, int]]:
    """
    Entrada: linhas do tipo:
      - "NF001; 123,45"
      - "123,45"
      - "Devolução; -10,00"
    Retorna: [(rotulo, valor_em_centavos)] na MESMA ORDEM da entrada.
    """
    if texto is None:
        return []
    linhas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    itens: List[Tuple[str, int]] = []
    for i, ln in enumerate(linhas, start=1):
        partes = re.split(r"[;\t]", ln)
        if len(partes) == 1:
            label = f"Item {i}"
            valor = parse_number_br_or_en(partes[0])
        else:
            label = (partes[0] or f"Item {i}").strip()
            valor = parse_number_br_or_en(partes[-1])

        if valor is None:
            continue
        itens.append((label, valor))
    return itens


def format_centavos(cents: int) -> str:
    """Formata em pt-BR (1.234,56) com sinal."""
    sinal = "-" if cents < 0 else ""
    cents = abs(cents)
    reais = cents // 100
    cent = cents % 100
    reais_str = f"{reais:,}".replace(",", ".")
    return f"{sinal}{reais_str},{cent:02d}"


# ----------------------------
# DP com negativos + tolerância
# ----------------------------

def subset_sum_with_tolerance(values: List[int], target: int, tolerance: int) -> Tuple[List[int], int]:
    """
    Aceita positivos e negativos.
    Procura soma em [target - tolerance, target + tolerance].
    Retorna (indices_usados, soma_encontrada) ou ([], 0) se não houver.
    Critério: menor |s-target|; em empate, preferir s <= target.
    """
    target = int(target)
    tolerance = max(0, int(tolerance))
    if not values:
        return [], 0

    min_sum = sum(v for v in values if v < 0)
    max_sum = sum(v for v in values if v > 0)

    lower = max(min_sum, target - tolerance)
    upper = min(max_sum, target + tolerance)
    if lower > upper:
        return [], 0

    offset = -min_sum
    width = max_sum - min_sum

    dp = [-1] * (width + 1)    # dp[i] = idx do item usado para formar soma (i-offset)
    prev = [-1] * (width + 1)  # prev[i] = índice anterior
    dp[0 + offset] = -2        # soma 0 presente

    for idx, v in enumerate(values):
        if v >= 0:
            # varre de trás pra frente
            for i in range(width, -1, -1):
                if dp[i] == -1:
                    j = i - v
                    if 0 <= j <= width and dp[j] != -1:
                        dp[i] = idx
                        prev[i] = j
        else:
            # negativo: varre de frente pra trás
            for i in range(0, width + 1):
                if dp[i] == -1:
                    j = i - v  # v<0 => i - v = i + |v|
                    if 0 <= j <= width and dp[j] != -1:
                        dp[i] = idx
                        prev[i] = j

    # selecionar melhor s dentro da faixa
    best_s = None
    best_key = None
    for s in range(lower, upper + 1):
        i = s + offset
        if 0 <= i <= width and dp[i] != -1:
            key = (abs(s - target), 0 if s <= target else 1)
            if best_key is None or key < best_key:
                best_key = key
                best_s = s

    if best_s is None:
        return [], 0

    # reconstrução dos índices usados (na ordem de entrada)
    indices: List[int] = []
    i = best_s + offset
    while i != 0 + offset:
        idx = dp[i]
        if idx < 0:
            break
        indices.append(idx)
        i = prev[i]
    indices.reverse()
    return indices, best_s


# ----------------------------
# Rotas
# ----------------------------

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        lista = request.form.get("lista", "")
        alvo_str = request.form.get("alvo", "")
        tolerancia_str = request.form.get("tolerancia", "0")

        alvo = parse_number_br_or_en(alvo_str)
        tolerancia = parse_number_br_or_en(tolerancia_str) or 0
        itens = parse_linhas_para_centavos(lista)

        if alvo is None or not itens:
            # volta pro formulário com aviso
            return render_template(
                "index.html",
                error="Verifique o valor do alvo, a tolerância e a lista de itens.",
                lista=lista,
                alvo=alvo_str,
                tolerancia=tolerancia_str
            )

        labels = [lab for lab, _ in itens]
        values = [val for _, val in itens]

        idxs, soma = subset_sum_with_tolerance(values, alvo, tolerancia)

        # Não achou: mantém o contrato do texto puro (front abre modal e preserva tela)
        if not idxs:
            return Response("não existe combinação para os valores informados", mimetype="text/plain")

        # Achou: devolve JSON com índices + textos formatados (front pinta as linhas)
        selecionados = []
        total = 0
        for i in idxs:
            selecionados.append({
                "index": i,                      # índice do item na entrada
                "label": labels[i],
                "valor_txt": format_centavos(values[i]),
                "valor_centavos": values[i],
            })
            total += values[i]

        payload = {
            "ok": True,
            "alvo_txt": format_centavos(alvo),
            "total_txt": format_centavos(total),
            "diferenca_txt": format_centavos(total - alvo),
            "tolerancia_txt": format_centavos(tolerancia),
            "exato": (total == alvo),
            "selecionados": selecionados,       # [{index, label, valor_txt, valor_centavos}, ...]
        }
        return jsonify(payload)

    # GET
    return render_template("index.html")


if __name__ == "__main__":
    # debug=True só em desenvolvimento local
    app.run(debug=True)
