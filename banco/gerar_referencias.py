"""
Gera o script 02_clyvo_referencias.sql a partir das planilhas de referência.
Uso: python gerar_referencias.py
"""

import csv
from pathlib import Path

PASTA = Path(__file__).resolve().parent

# Procura a pasta referencias/ (ao lado desta pasta ou acima dela)
PASTA_REF = next((p for base in (PASTA, PASTA.parent, PASTA.parent.parent)
                  for p in (base / "referencias", base / "dados" / "referencias")
                  if (p / "ref_peso.csv").exists()), PASTA)
ARQUIVO_SAIDA = PASTA / "02_clyvo_referencias.sql"

SINAL = {"aumenta": 1, "diminui": -1, "": 0}


def ler(nome):
    with open(PASTA_REF / nome, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def txt(v):
    """Literal de texto Oracle (NULL quando vazio)."""
    v = (v or "").strip()
    return "NULL" if v == "" else "'" + v.replace("'", "''") + "'"


def num(v):
    """Literal numérico (NULL quando vazio)."""
    v = (v or "").strip()
    return "NULL" if v == "" else f"{float(v):g}"


def montar():
    peso = ler("ref_peso.csv")
    catalogo = ler("catalogo_doencas.csv")
    cronicas = {(d["doenca"], d["especie"]): d for d in ler("ref_doencas.csv")}
    predisp = ler("ref_predisposicao.csv")
    vacinas = ler("ref_vacinas.csv")
    consumo = ler("ref_consumo.csv")
    racoes = ler("ref_racoes.csv")

    especies = sorted({r["especie"] for r in peso} | {c["especie"] for c in catalogo})

    # ---- doenças: catálogo + idade de risco e sinais das crônicas ----------
    doencas, id_doenca = [], {}
    for i, c in enumerate(catalogo, start=1):
        chave = (c["doenca"], c["especie"])
        cr = cronicas.get(chave, {})
        tipo = "CRONICA" if c["tipo"].startswith("cronica") else "INFECCIOSA"
        fonte = c["fonte"]
        link = c["link"]
        if cr:  # para as crônicas, a fonte é a da idade e a do sinal (ref_doencas.csv)
            fonte = f"Idade: {cr['fonte_idade']} | Sinal: {cr['fonte_sinal']}"
            link = cr["link_sinal"]
        id_doenca[chave] = i
        doencas.append([
            str(i), txt(c["doenca"]), txt(c["especie"]), txt(tipo), txt(c["contagiosa"]), txt(c["zoonose"]),
            txt(c["monitora_surto"]), txt(c["alerta_caso_unico"]),
            num(c["mes_inicio_pico"]), num(c["mes_fim_pico"]),
            num(cr.get("idade_risco_anos", "")),
            str(SINAL[cr.get("comida", "") or ""]), str(SINAL[cr.get("agua", "") or ""]),
            str(SINAL[cr.get("movimento", "") or ""]),
            txt(cr.get("momento_sinal", "").upper()),
            txt(c["transmissao"]), txt(c["prevencao"]), txt(cr.get("sinais_clinicos", "")),
            txt(c["dados_brasil"]), txt(fonte), txt(link)])
    faltando = set(cronicas) - set(id_doenca)
    assert not faltando, f"doenças de ref_doencas.csv fora do catálogo: {faltando}"

    # ---- peso ----------------------------------------------------------------
    peso_rows = []
    for i, r in enumerate(peso, start=1):
        sexo = {"M": "M", "F": "F", "Ambos": "A"}[r["sexo"]]
        peso_rows.append([str(i), txt(r["especie"]), txt(r["raca"]), txt(r["raca_original"]), txt(sexo),
                          num(r["peso_min_kg"]), num(r["peso_max_kg"]), num(r["media_kg"]), num(r["desvio_kg"]),
                          num(r["n_animais"].split(".")[0] if r["n_animais"] else ""), txt(r["fonte"])])

    # ---- predisposições ------------------------------------------------------
    pred_rows = []
    for i, p in enumerate(predisp, start=1):
        chave = (p["doenca"], p["especie"])
        assert chave in id_doenca, f"predisposição com doença fora do catálogo: {chave}"
        pred_rows.append([str(i), txt(p["especie"]), txt(p["raca"]), str(id_doenca[chave]),
                          txt(p["tipo"].upper()), num(p["razao_risco"]), txt(p["medida"]), txt(p["observacao"]),
                          txt(p["fonte"]), txt(p["link"])])

    # ---- vacinas -------------------------------------------------------------
    vac_rows, vac_id, vd_rows = [], {}, []
    for v in vacinas:
        if v["vacina"] not in vac_id:
            vac_id[v["vacina"]] = len(vac_id) + 1
            vac_rows.append([str(vac_id[v["vacina"]]), txt(v["vacina"]), txt(v["composicao"]),
                             num(v["reforco_meses"]), txt(v["classificacao_wsava"]),
                             txt(f"Reforço: {v['fonte_reforco']} | Composição: {v['fonte_composicao']}"),
                             txt(v["link"])])
        chave = (v["doenca"], v["especie"])
        assert chave in id_doenca, f"vacina com doença fora do catálogo: {chave}"
        vd_rows.append([str(len(vd_rows) + 1), str(vac_id[v["vacina"]]), str(id_doenca[chave]), txt(v["cobertura"])])

    # ---- consumo e rações ----------------------------------------------------
    cons_rows = [[str(i), txt(c["especie"]), txt(c["castrado"]), num(c["coef_rer"]), num(c["expoente"]),
                  num(c["fator_manutencao"]), num(c["coef_agua_ml"]), num(c["tolerancia"]),
                  txt(f"Comida: {c['fonte_comida']} | Água: {c['fonte_agua']} | Tolerância: {c['fonte_tolerancia']}")]
                 for i, c in enumerate(consumo, start=1)]
    rac_rows = [[str(i), txt(r["especie"]), txt(r["produto"]), txt(r["fabricante"]), txt(r["para_castrados"]),
                 num(r["kcal_kg"]), num(r["umidade_max_pct"]), txt(r["link"])]
                for i, r in enumerate(racoes, start=1)]

    esp_rows = [[str(i), txt(e)] for i, e in enumerate(especies, start=1)]

    return [
        ("Espécies", "T_CLYVO_ESPECIE", ["id_especie", "nm_especie"], esp_rows),
        ("Catálogo de doenças (catalogo_doencas.csv + ref_doencas.csv)", "T_CLYVO_DOENCA",
         ["id_doenca", "nm_doenca", "especie_alvo", "tp_doenca", "contagiosa", "zoonose", "monitora_surto",
          "alerta_caso_unico", "mes_inicio_pico", "mes_fim_pico", "idade_risco_anos", "sinal_comida", "sinal_agua",
          "sinal_movimento", "momento_sinal", "ds_transmissao", "ds_prevencao", "ds_sinais_clinicos",
          "ds_dados_brasil", "ds_fonte", "ds_link"], doencas),
        ("Peso ideal por espécie, raça e sexo (ref_peso.csv)", "T_CLYVO_REF_PESO_RACA",
         ["id_ref_peso", "especie_animal", "raca_animal", "raca_original", "sexo_animal", "peso_min_kg",
          "peso_max_kg", "media_kg", "desvio_kg", "n_animais", "ds_fonte"], peso_rows),
        ("Predisposições e proteções por raça (ref_predisposicao.csv)", "T_CLYVO_PREDISP_RACA",
         ["id_predisp_raca", "especie_animal", "raca_animal", "id_doenca", "tp_relacao", "vl_razao_risco",
          "ds_medida", "ds_observacao", "ds_fonte", "ds_link"], pred_rows),
        ("Vacinas (ref_vacinas.csv)", "T_CLYVO_VACINA",
         ["id_vacina", "nm_vacina", "ds_composicao", "qt_reforco_meses", "ds_classificacao", "ds_fonte", "ds_link"],
         vac_rows),
        ("Vacina x doença (ref_vacinas.csv)", "T_CLYVO_VACINA_DOENCA",
         ["id_vacina_doenca", "id_vacina", "id_doenca", "ds_cobertura"], vd_rows),
        ("Fórmulas de consumo esperado (ref_consumo.csv)", "T_CLYVO_REF_CONSUMO",
         ["id_ref_consumo", "especie_animal", "castrado", "coef_rer", "expoente", "fator_manutencao",
          "coef_agua_ml", "tolerancia", "ds_fonte"], cons_rows),
        ("Rações de referência (ref_racoes.csv)", "T_CLYVO_REF_RACAO",
         ["id_ref_racao", "especie_animal", "nm_produto", "nm_fabricante", "para_castrados", "kcal_kg",
          "umidade_max_pct", "ds_link"], rac_rows),
    ]


def escrever(blocos):
    linhas = ["-- ============================================================================",
              "--  Script 02: Tabelas de referência (gerado por gerar_referencias.py)",
              "--  Origem: planilhas da pasta referencias.",
              "--  Ordem de execução: 01 -> 02 -> 03",
              "-- ============================================================================",
              "SET DEFINE OFF;", ""]
    for titulo, tabela, colunas, registros in blocos:
        linhas.append(f"-- {titulo}")
        for reg in registros:
            linhas.append(f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join(reg)});")
        linhas.append("COMMIT;")
        linhas.append("")
    linhas.append("-- Contadores IDENTITY depois dos IDs inseridos explicitamente")
    for _, tabela, colunas, _ in blocos:
        linhas.append(f"ALTER TABLE {tabela} MODIFY ({colunas[0]} GENERATED BY DEFAULT ON NULL AS IDENTITY "
                      f"(START WITH LIMIT VALUE));")
    linhas.append("")
    linhas.append("-- Conferência")
    partes = [f"SELECT '{t}' AS tabela, COUNT(*) AS qtd FROM {t}" for _, t, _, _ in blocos]
    linhas.append("\nUNION ALL ".join(partes) + ";")
    ARQUIVO_SAIDA.write_text("\n".join(linhas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    blocos = montar()
    escrever(blocos)
    print(f"Arquivo {ARQUIVO_SAIDA.name} gerado a partir de {PASTA_REF}")
    for titulo, tabela, _, registros in blocos:
        print(f"  {tabela}: {len(registros)}")
