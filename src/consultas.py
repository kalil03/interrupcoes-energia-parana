"""Consultas SQL da Etapa 3. Cada uma responde a uma pergunta sobre os dados."""

CONSULTAS = {}


def consulta(nome, pergunta):
    def registrar(sql):
        CONSULTAS[nome] = (pergunta, sql.strip())
        return sql

    return registrar


consulta("mensal", "Como as interrupções não programadas evoluíram mês a mês?")("""
WITH meses AS (
    SELECT DATE_TRUNC('month', data) AS mes,
           COUNT(*) AS dias_no_mes,
           COUNT(*) FILTER (WHERE NOT sem_registro_interrupcao) AS dias_com_dados
    FROM base
    WHERE data <= (SELECT MAX(data) FROM dia_np)
    GROUP BY 1
),
np AS (
    SELECT DATE_TRUNC('month', data) AS mes,
           AVG(interrupcoes) AS interrupcoes_dia,
           AVG(uc_afetadas) AS uc_afetadas_dia,
           AVG(uc_horas) AS uc_horas_dia,
           MEDIAN(duracao_mediana_h) AS duracao_mediana_h
    FROM dia_np
    GROUP BY 1
)
SELECT m.mes,
       periodo_de(m.mes) AS periodo,
       m.dias_com_dados,
       m.dias_no_mes,
       n.* EXCLUDE (mes),
       -- média móvel de 12 meses: tira a sazonalidade e mostra a tendência
       AVG(n.interrupcoes_dia) OVER (ORDER BY m.mes ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS media_movel_12m
FROM meses m
LEFT JOIN np n USING (mes)
ORDER BY m.mes
""")

consulta("por_periodo", "Em média, quantas interrupções por dia antes e depois da privatização?")("""
WITH resumo AS (
    SELECT periodo,
           MIN(data) AS inicio,
           MAX(data) AS fim,
           COUNT(*) AS dias,
           AVG(interrupcoes) AS interrupcoes_dia,
           AVG(conjuntos_afetados) AS conjuntos_afetados_dia,
           AVG(uc_afetadas) AS uc_afetadas_dia,
           AVG(uc_horas) AS uc_horas_dia,
           MEDIAN(duracao_mediana_h) AS duracao_mediana_h,
           AVG(chuva_max) AS chuva_max_media
    FROM dia_np
    GROUP BY periodo
)
SELECT *,
       -- variação em relação ao período antes da privatização (primeira linha)
       interrupcoes_dia / FIRST_VALUE(interrupcoes_dia) OVER (ORDER BY periodo) - 1 AS var_interrupcoes,
       uc_horas_dia / FIRST_VALUE(uc_horas_dia) OVER (ORDER BY periodo) - 1 AS var_uc_horas
FROM resumo
ORDER BY periodo
""")

consulta("mesmo_mes", "Comparando o mesmo mês do ano, depois da privatização há mais interrupções?")("""
WITH por_mes AS (
    SELECT mes,
           COUNT(*) FILTER (WHERE periodo = '1 antes') AS dias_antes,
           COUNT(*) FILTER (WHERE periodo = '2 depois') AS dias_depois,
           AVG(interrupcoes) FILTER (WHERE periodo = '1 antes') AS antes,
           AVG(interrupcoes) FILTER (WHERE periodo = '2 depois') AS depois,
           AVG(chuva_max) FILTER (WHERE periodo = '1 antes') AS chuva_antes,
           AVG(chuva_max) FILTER (WHERE periodo = '2 depois') AS chuva_depois
    FROM dia_np
    GROUP BY mes
)
SELECT *, depois / antes - 1 AS variacao
FROM por_mes
ORDER BY mes
""")

consulta("dec_fec", "Indicadores parecidos com DEC e FEC, acumulados em 12 meses (2022–2025)")("""
WITH consumidores AS (
    -- consumidores de cada conjunto no mês (maior valor informado nos registros)
    SELECT DATE_TRUNC('month', data) AS mes, conjunto, MAX(consumidores_conjunto) AS consumidores
    FROM micro
    WHERE data < DATE '2026-01-01'
    GROUP BY ALL
),
total AS (
    SELECT mes, SUM(consumidores) AS consumidores FROM consumidores GROUP BY mes
),
np AS (
    SELECT DATE_TRUNC('month', data) AS mes,
           SUM(uc_horas) AS uc_horas,
           SUM(uc_eventos) AS uc_eventos
    FROM micro
    WHERE nao_programada AND data < DATE '2026-01-01'
    GROUP BY mes
),
mensal AS (
    SELECT n.mes,
           n.uc_horas / t.consumidores AS dec_mes,     -- horas sem energia por consumidor
           n.uc_eventos / t.consumidores AS fec_mes    -- interrupções por consumidor
    FROM np n
    JOIN total t USING (mes)
)
SELECT mes,
       periodo_de(mes) AS periodo,
       dec_mes,
       fec_mes,
       COUNT(*) OVER janela AS meses_na_janela,
       SUM(dec_mes) OVER janela AS dec_12m,
       SUM(fec_mes) OVER janela AS fec_12m
FROM mensal
WINDOW janela AS (ORDER BY mes RANGE BETWEEN INTERVAL 11 MONTH PRECEDING AND CURRENT ROW)
ORDER BY mes
""")

consulta("causas", "As causas das interrupções mudaram depois da privatização? (2022–2025)")("""
WITH registros AS (
    SELECT periodo_de(data) AS periodo,
           COALESCE(NULLIF(TRIM(regexp_extract(UPPER(fato_gerador), 'PROGRAMADA-([^-]+)', 1)), ''),
                    'NAO INFORMADA') AS causa
    FROM micro
    WHERE nao_programada AND esquema_aneel = 'ate2025'
),
contagem AS (
    SELECT periodo, causa, COUNT(*) AS registros FROM registros GROUP BY ALL
),
dias AS (
    SELECT periodo, COUNT(*) AS dias FROM dia_np GROUP BY periodo
)
SELECT c.periodo,
       c.causa,
       c.registros,
       c.registros / d.dias AS registros_por_dia,
       c.registros / SUM(c.registros) OVER (PARTITION BY c.periodo) AS participacao
FROM contagem c
JOIN dias d USING (periodo)
ORDER BY c.causa, c.periodo
""")

consulta("duracao", "As interrupções passaram a durar mais depois da privatização?")("""
SELECT periodo_de(data) AS periodo,
       COUNT(*) AS registros,
       AVG(duracao_h) AS media_h,
       MEDIAN(duracao_h) AS mediana_h,
       quantile_cont(duracao_h, 0.9) AS p90_h,
       AVG(CAST(duracao_h > 3 AS DOUBLE)) AS frac_mais_3h,
       AVG(CAST(duracao_h > 24 AS DOUBLE)) AS frac_mais_24h
FROM micro
WHERE nao_programada AND NOT duracao_suspeita AND duracao_h IS NOT NULL
GROUP BY 1
ORDER BY 1
""")

consulta("clima_periodo", "Em dias de chuva ou vento forte, a Copel passou a ter mais ou menos interrupções?")("""
WITH limiares AS (
    -- dia extremo: chuva ou rajada acima do percentil 95 do período todo
    SELECT quantile_cont(chuva_max, 0.95) AS p95_chuva,
           quantile_cont(rajada_max, 0.95) AS p95_rajada
    FROM dia_np
    WHERE chuva_max IS NOT NULL
),
dias AS (
    SELECT d.*, (d.chuva_max >= l.p95_chuva OR d.rajada_max >= l.p95_rajada) AS extremo
    FROM dia_np d, limiares l
    WHERE d.chuva_max IS NOT NULL
)
SELECT periodo,
       COUNT(*) FILTER (WHERE extremo) AS dias_extremos,
       COUNT(*) FILTER (WHERE NOT extremo) AS dias_normais,
       AVG(interrupcoes) FILTER (WHERE extremo) AS media_dia_extremo,
       AVG(interrupcoes) FILTER (WHERE NOT extremo) AS media_dia_normal,
       media_dia_extremo / media_dia_normal AS razao
FROM dias
GROUP BY periodo
ORDER BY periodo
""")

consulta("recorrencia", "Quando um conjunto falha, quanto tempo leva para falhar de novo?")("""
WITH cobertura AS (
    -- contador de dias sem dados da ANEEL, para descartar intervalos que atravessam lacunas
    SELECT data, SUM(CAST(sem_registro_interrupcao AS INT)) OVER (ORDER BY data) AS lacunas
    FROM base
),
falhas AS (
    SELECT c.conjunto, c.data, k.lacunas
    FROM conjunto_dia c
    JOIN cobertura k USING (data)
    WHERE c.interrupcoes_nao_programadas > 0
),
intervalos AS (
    SELECT conjunto, data,
           date_diff('day', LAG(data) OVER w, data) AS dias_desde_anterior,
           lacunas - LAG(lacunas) OVER w AS lacunas_no_intervalo
    FROM falhas
    WINDOW w AS (PARTITION BY conjunto ORDER BY data)
)
SELECT periodo_de(data) AS periodo,
       COUNT(*) AS intervalos,
       AVG(CAST(dias_desde_anterior = 1 AS DOUBLE)) AS frac_no_dia_seguinte,
       AVG(CAST(dias_desde_anterior <= 7 AS DOUBLE)) AS frac_em_ate_7_dias,
       MEDIAN(dias_desde_anterior) AS mediana_dias,
       AVG(dias_desde_anterior) AS media_dias
FROM intervalos
WHERE dias_desde_anterior IS NOT NULL AND lacunas_no_intervalo = 0
GROUP BY 1
ORDER BY 1
""")

consulta("carga_temperatura", "A carga máxima do Sul muda com a temperatura? (dias úteis)")("""
WITH uteis AS (
    SELECT temp_media,
           -- carga dividida pela média do ano, para o crescimento anual não atrapalhar
           carga_max / AVG(carga_max) OVER (PARTITION BY YEAR(data)) AS carga_relativa
    FROM dia_carga
    WHERE n_ufs_feriado = 0 AND dia_semana < 5 AND temp_media IS NOT NULL
)
SELECT FLOOR(temp_media / 2) * 2 AS faixa_inicio,
       COUNT(*) AS dias,
       AVG(carga_relativa) AS carga_relativa
FROM uteis
GROUP BY 1
HAVING COUNT(*) >= 10
ORDER BY 1
""")

consulta("feriados", "Quanto a carga cai num feriado em relação aos dias úteis parecidos?")("""
WITH feriados AS (
    SELECT data, carga_max, n_ufs_feriado,
           COALESCE(feriado_nome, 'feriado estadual SC/RS') AS feriado
    FROM dia_carga
    WHERE n_ufs_feriado > 0 AND dia_semana < 5
),
referencias AS (
    -- mesmo dia da semana 7 e 14 dias antes e depois, sem feriado
    SELECT f.data, AVG(r.carga_max) AS carga_referencia, COUNT(*) AS n_referencias
    FROM feriados f
    JOIN dia_carga r ON r.n_ufs_feriado = 0 AND ABS(date_diff('day', f.data, r.data)) IN (7, 14)
    GROUP BY f.data
)
SELECT f.data, f.feriado, f.n_ufs_feriado, f.carga_max, r.carga_referencia,
       f.carga_max / r.carga_referencia - 1 AS variacao
FROM feriados f
JOIN referencias r USING (data)
WHERE r.n_referencias >= 2
ORDER BY variacao
""")


def rodar(con, nome, mostrar_sql=True):
    """Mostra a pergunta e o SQL, executa e devolve o resultado como DataFrame."""
    pergunta, sql = CONSULTAS[nome]
    if mostrar_sql:
        print(f"Pergunta: {pergunta}\n\n{sql}\n")
    return con.sql(sql).df()
