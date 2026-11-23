"""Conexão DuckDB com os Parquets da Etapa 2 e visões usadas na investigação."""
import duckdb

from .config import PROCESSADOS

PRIVATIZACAO = "2023-08-01"
INICIO_ESQUEMA_2026 = "2026-01-01"

ARQUIVOS = {
    "base": "base_diaria_copel_pr.parquet",
    "carga_d1": "carga_sul_d1.parquet",
    "conjunto_dia": "interrupcoes_nao_programadas_conjunto_dia.parquet",
    "micro": "interrupcoes_copel.parquet",
}

VISOES = {
    "base": """
        SELECT * REPLACE (CAST(data AS DATE) AS data)
        FROM read_parquet('{caminho}')
    """,
    "carga_d1": """
        SELECT * REPLACE (CAST(data_origem AS DATE) AS data_origem, CAST(data_alvo AS DATE) AS data_alvo)
        FROM read_parquet('{caminho}')
    """,
    "conjunto_dia": """
        SELECT * REPLACE (CAST(data AS DATE) AS data)
        FROM read_parquet('{caminho}')
    """,
    # Só as colunas usadas: o arquivo tem milhões de linhas e muitas colunas.
    # UC-horas de eventos com mais de 7 dias (marcados na Etapa 2) ficam fora das somas.
    "micro": """
        SELECT CAST(data AS DATE) AS data,
               id_interrupcao,
               IdeConjuntoUnidadeConsumidora AS conjunto,
               NumConsumidorConjunto AS consumidores_conjunto,
               nao_programada,
               esquema_aneel,
               duracao_h_valida AS duracao_h,
               duracao_suspeita_7dias AS duracao_suspeita,
               uc_eventos,
               CASE WHEN duracao_suspeita_7dias THEN NULL ELSE uc_horas END AS uc_horas,
               DscFatoGeradorInterrupcao AS fato_gerador
        FROM read_parquet('{caminho}')
    """,
}

# Período de cada data: antes da privatização, depois (mesmo esquema ANEEL) e 2026 (esquema novo).
MACRO_PERIODO = f"""
CREATE OR REPLACE MACRO periodo_de(d) AS
    CASE WHEN d < DATE '{PRIVATIZACAO}' THEN '1 antes'
         WHEN d < DATE '{INICIO_ESQUEMA_2026}' THEN '2 depois'
         ELSE '3 em 2026 (esquema novo)' END
"""

# Um dia por linha, só nos dias em que a ANEEL publicou registros da Copel.
DIA_NP = """
CREATE OR REPLACE VIEW dia_np AS
WITH np AS (
    SELECT data,
           COUNT(DISTINCT id_interrupcao) AS interrupcoes,
           COUNT(DISTINCT conjunto) AS conjuntos_afetados,
           SUM(uc_eventos) AS uc_afetadas,
           SUM(uc_horas) AS uc_horas,
           MEDIAN(duracao_h) FILTER (WHERE NOT duracao_suspeita) AS duracao_mediana_h
    FROM micro
    WHERE nao_programada
    GROUP BY data
)
SELECT b.data,
       periodo_de(b.data) AS periodo,
       YEAR(b.data) AS ano,
       MONTH(b.data) AS mes,
       b.dia_semana,
       b.feriado_br_pr AS feriado,
       b.clima_max_precipitacao_mm AS chuva_max,
       b.clima_max_rajada_kmh AS rajada_max,
       np.* EXCLUDE (data)
FROM base b
JOIN np USING (data)
WHERE NOT b.sem_registro_interrupcao
"""

# Um dia por linha com a carga máxima do Sul, feriados de PR/SC/RS e temperatura do PR.
DIA_CARGA = """
CREATE OR REPLACE VIEW dia_carga AS
SELECT c.data_alvo AS data,
       c.carga_max_sul_d1_mwmed AS carga_max,
       CAST(c.feriado_pr_d1 AS INT) + CAST(c.feriado_sc_d1 AS INT) + CAST(c.feriado_rs_d1 AS INT) AS n_ufs_feriado,
       c.dia_semana_d1 AS dia_semana,
       b.feriado_nome,
       b.clima_media_temperature_2m_mean AS temp_media
FROM carga_d1 c
JOIN base b ON b.data = c.data_alvo
WHERE c.carga_max_sul_d1_mwmed IS NOT NULL
"""


def conectar(processados=PROCESSADOS):
    faltando = [a for a in ARQUIVOS.values() if not (processados / a).is_file()]
    if faltando:
        raise FileNotFoundError(
            f"Execute antes notebooks/01_preparacao_dados.ipynb. Ausentes em {processados}: {faltando}"
        )
    con = duckdb.connect()
    for nome, arquivo in ARQUIVOS.items():
        caminho = (processados / arquivo).as_posix()
        con.execute(f"CREATE VIEW {nome} AS " + VISOES[nome].format(caminho=caminho))
    for comando in [MACRO_PERIODO, DIA_NP, DIA_CARGA]:
        con.execute(comando)
    return con


def tamanhos(con):
    visoes = [*ARQUIVOS, "dia_np", "dia_carga"]
    return {v: con.sql(f"SELECT COUNT(*) FROM {v}").fetchone()[0] for v in visoes}
