"""Acesso ao banco Oracle da Clyvo Vet."""

import os
from datetime import date, datetime, timedelta

import pandas as pd


def conectar():
    """Abre uma conexão com o Oracle usando as credenciais do arquivo .env."""
    import oracledb
    return oracledb.connect(user=os.getenv("CLYVO_DB_USER"), password=os.getenv("CLYVO_DB_PASSWORD"),
                            dsn=os.getenv("CLYVO_DB_DSN"))


def consultar(con, sql, parametros=None):
    """Executa um SELECT e devolve uma tabela (nomes das colunas em minúsculo)."""
    cur = con.cursor()
    cur.execute(sql, parametros or {})
    colunas = [c[0].lower() for c in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=colunas)


def para_data(valor):
    """Converte o valor do banco em data."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return datetime.fromisoformat(str(valor)[:19]).date()


# Animais com responsável e endereço
SQL_ANIMAIS = """
SELECT a.id_animal, a.nm_animal, a.dt_nascimento_animal, a.peso_animal, a.especie_animal, a.raca_animal,
       a.sexo_animal, a.castrado, a.kcal_kg_racao, r.nm_responsavel, r.nr_telefone_responsavel,
       e.cidade, e.bairro
  FROM T_CLYVO_ANIMAL a
  JOIN T_CLYVO_RESPONSAVEL r          ON r.id_responsavel = a.id_responsavel
  LEFT JOIN T_CLYVO_ENDERECO_ANIMAL e ON e.id_animal = a.id_animal
 ORDER BY a.id_animal
"""

# Leituras do sensor no período analisado
SQL_LEITURAS = """
SELECT id_animal, dt_leitura, consumo_comida_g, consumo_agua_ml, nivel_movimento
  FROM T_CLYVO_LEITURA_SENSOR
 WHERE dt_leitura >= :inicio
 ORDER BY id_animal, dt_leitura
"""

# Situação das vacinas
SQL_VACINACOES = "SELECT id_animal, nm_vacina, st_vacinacao FROM T_CLYVO_VACINACAO"

# Data da última consulta de cada animal
SQL_ULTIMA_CONSULTA = """
SELECT id_animal, MAX(dt_consulta) AS ultima
  FROM T_CLYVO_CONSULTA
 WHERE st_consulta = 'PASSADA' AND dt_consulta <= :hoje
 GROUP BY id_animal
"""

# Doenças infecciosas (para o registro de diagnóstico)
SQL_DOENCAS_INFECCIOSAS = """
SELECT id_doenca, nm_doenca, especie_alvo
  FROM T_CLYVO_DOENCA
 WHERE tp_doenca = 'INFECCIOSA'
 ORDER BY especie_alvo, nm_doenca
"""


def carregar_dados(con, inicio, hoje):
    """Lê do banco tudo o que os vigias precisam."""
    return {
        "animais": consultar(con, SQL_ANIMAIS),
        "leituras": consultar(con, SQL_LEITURAS, {"inicio": inicio}),
        "vacinacoes": consultar(con, SQL_VACINACOES),
        "ultimas_consultas": consultar(con, SQL_ULTIMA_CONSULTA, {"hoje": hoje}),
    }


def doencas_infecciosas(con):
    return consultar(con, SQL_DOENCAS_INFECCIOSAS)


def registrar_diagnostico(con, id_animal, id_doenca, data_consulta, historico):
    """Grava uma consulta já realizada com o diagnóstico informado."""
    import oracledb
    cur = con.cursor()
    id_vet_cli = cur.execute("SELECT MIN(id_clinica_vet) FROM T_CLYVO_CLINICA_VET").fetchone()[0]
    novo_id = cur.var(oracledb.NUMBER)
    cur.execute("""INSERT INTO T_CLYVO_CONSULTA (historico_consulta, st_consulta, dt_consulta, id_vet_cli, id_animal)
                   VALUES (:historico, 'PASSADA', :data, :vet, :animal)
                   RETURNING id_consulta INTO :novo_id""",
                {"historico": historico[:200], "data": data_consulta, "vet": id_vet_cli,
                 "animal": id_animal, "novo_id": novo_id})
    id_consulta = int(novo_id.getvalue()[0])
    cur.execute("INSERT INTO T_CLYVO_CONSULTA_DOENCA (id_consulta, id_doenca) VALUES (:consulta, :doenca)",
                {"consulta": id_consulta, "doenca": id_doenca})
    con.commit()
    return id_consulta


def inserir_leituras(con, id_animal, comida, agua, movimento, dias):
    """Grava novas leituras diárias (simulando o ESP32), depois da última leitura do animal."""
    cur = con.cursor()
    cur.execute("SELECT MAX(dt_leitura) FROM T_CLYVO_LEITURA_SENSOR WHERE id_animal = :id", {"id": id_animal})
    ultima = cur.fetchone()[0]
    ultima = datetime.fromisoformat(str(ultima)[:19]) if ultima is not None else datetime.now().replace(hour=20)
    linhas = [{"id": id_animal, "dt": (ultima + timedelta(days=i + 1)).replace(microsecond=0), "comida": comida,
               "agua": agua, "mov": movimento} for i in range(dias)]
    cur.executemany("""INSERT INTO T_CLYVO_LEITURA_SENSOR (id_animal, dt_leitura, consumo_comida_g, consumo_agua_ml,
                                                          nivel_movimento, id_dispositivo)
                       VALUES (:id, :dt, :comida, :agua, :mov, 'simulacao-app')""", linhas)
    con.commit()


def remover_demonstracoes(con):
    """Apaga os diagnósticos e as leituras registrados pela aplicação na demonstração."""
    cur = con.cursor()
    cur.execute("DELETE FROM T_CLYVO_LEITURA_SENSOR WHERE id_dispositivo = 'simulacao-app'")
    filtro = "SELECT id_consulta FROM T_CLYVO_CONSULTA WHERE historico_consulta LIKE '[Demonstração]%'"
    cur.execute(f"DELETE FROM T_CLYVO_CONSULTA_DOENCA WHERE id_consulta IN ({filtro})")
    cur.execute("DELETE FROM T_CLYVO_CONSULTA WHERE historico_consulta LIKE '[Demonstração]%'")
    removidos = cur.rowcount
    con.commit()
    return removidos


def salvar_alertas(con, alertas):
    """Encerra os alertas ativos e grava os novos em T_CLYVO_ALERTA."""
    cur = con.cursor()
    cur.execute("UPDATE T_CLYVO_ALERTA SET st_alerta = 'RESOLVIDO' WHERE st_alerta = 'ATIVO'")
    if alertas:
        cur.executemany("""INSERT INTO T_CLYVO_ALERTA (tp_alerta, vigia_origem, nivel_risco, probabilidade, ds_motivo,
                                                       ds_recomendacao, st_notificacao, id_animal, cidade, bairro, id_doenca)
                           VALUES (:tp_alerta, :vigia_origem, :nivel_risco, :probabilidade, :ds_motivo,
                                   :ds_recomendacao, 'SIMULADO', :id_animal, :cidade, :bairro, :id_doenca)""", alertas)
    con.commit()


def ids_doencas(con):
    tabela = consultar(con, "SELECT id_doenca, nm_doenca, especie_alvo FROM T_CLYVO_DOENCA")
    return {(r.nm_doenca, r.especie_alvo): int(r.id_doenca) for r in tabela.itertuples()}
