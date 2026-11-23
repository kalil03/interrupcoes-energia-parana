"""Testes estatísticos da Etapa 3."""
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from .banco import PRIVATIZACAO

ALFA = 0.05
MARGEM = 0.10  # diferença de até 10% para cima ou para baixo é considerada pequena
HAC = {"cov_type": "HAC", "cov_kwds": {"maxlags": 7}}  # erros robustos à correlação entre dias vizinhos


def preparar_dias(dia_np):
    """Acrescenta as variáveis usadas nos modelos à tabela diária de interrupções."""
    d = dia_np.sort_values("data").reset_index(drop=True).copy()
    d["depois"] = d.data.ge(PRIVATIZACAO).astype(int)
    d["esquema_2026"] = d.data.dt.year.ge(2026).astype(int)
    d["feriado"] = d.feriado.astype(int)
    d["chuva_10mm"] = d.chuva_max / 10
    d["rajada_10kmh"] = d.rajada_max / 10
    d["tendencia"] = (d.data - pd.Timestamp("2022-01-01")).dt.days / 365.25
    d["tendencia_depois"] = ((d.data - pd.Timestamp(PRIVATIZACAO)).dt.days / 365.25).clip(lower=0)
    d["log_uc_horas"] = np.log1p(d.uc_horas)
    limites = d[["chuva_max", "rajada_max"]].quantile(0.95)
    d["extremo"] = (d.chuva_max.ge(limites.chuva_max) | d.rajada_max.ge(limites.rajada_max)).astype(int)
    return d.dropna(subset=["chuva_max", "rajada_max"])


def ajustar_nb(formula, dados):
    """Binomial negativa: dispersão por máxima verossimilhança, reajuste como GLM com erros HAC."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ajuste = smf.negativebinomial(formula, dados).fit(disp=0, maxiter=500)
        if not ajuste.mle_retvals.get("converged", False):
            raise RuntimeError("não convergiu")
        alfa = ajuste.params["alpha"]
    except Exception:  # se não convergir: estimativa de Cameron e Trivedi a partir de um Poisson
        poisson = smf.glm(formula, dados, family=sm.families.Poisson()).fit()
        y, mu = poisson.model.endog, poisson.mu
        alfa = max(float(np.sum((y - mu) ** 2 - y) / np.sum(mu ** 2)), 1e-6)
    return smf.glm(formula, dados, family=sm.families.NegativeBinomial(alpha=alfa)).fit(**HAC)


def razao(modelo, termo):
    """Efeito multiplicativo de um termo (exp do coeficiente) com IC de 95%."""
    ic = modelo.conf_int().loc[termo]
    return {"razão": np.exp(modelo.params[termo]), "IC95% inf": np.exp(ic[0]),
            "IC95% sup": np.exp(ic[1]), "p": modelo.pvalues[termo]}


def classificar(r):
    """Lê o intervalo de confiança da razão. 'Sem diferença' só quando o IC inteiro cabe na margem."""
    dentro_da_margem = r["IC95% inf"] >= 1 - MARGEM and r["IC95% sup"] <= 1 + MARGEM
    if r["p"] < ALFA:
        sentido = "aumento" if r["razão"] > 1 else "redução"
        return f"{sentido} pequeno (IC dentro de ±{MARGEM:.0%})" if dentro_da_margem else sentido
    if dentro_da_margem:
        return f"sem diferença relevante (IC dentro de ±{MARGEM:.0%})"
    return "inconclusivo (IC largo)"


def teste_privatizacao(dias):
    """Compara antes e depois de ago/2023 controlando mês, dia da semana, feriado, chuva e vento."""
    controles = "C(mes) + C(dia_semana) + feriado + chuva_10mm + rajada_10kmh"
    mesmo_esquema = dias.loc[dias.esquema_2026.eq(0)]
    modelos = {
        "interrupções/dia · 2022–2025": (
            ajustar_nb(f"interrupcoes ~ depois + {controles}", mesmo_esquema), "depois"),
        "interrupções/dia · com 2026 (controle do esquema)": (
            ajustar_nb(f"interrupcoes ~ depois + esquema_2026 + {controles}", dias), "depois"),
        "UC-horas/dia · 2022–2025": (
            smf.ols(f"log_uc_horas ~ depois + {controles}", mesmo_esquema).fit(**HAC), "depois"),
        "conjuntos afetados/dia · 2022–2025": (
            ajustar_nb(f"conjuntos_afetados ~ depois + {controles}", mesmo_esquema), "depois"),
    }
    tendencia = ajustar_nb(f"interrupcoes ~ tendencia + depois + tendencia_depois + {controles}", mesmo_esquema)
    modelos["salto em ago/2023 (com tendência)"] = (tendencia, "depois")
    modelos["mudança de tendência por ano"] = (tendencia, "tendencia_depois")
    linhas = {nome: razao(modelo, termo) for nome, (modelo, termo) in modelos.items()}
    tabela = pd.DataFrame(linhas).T
    tabela["leitura"] = [classificar(r) for _, r in tabela.iterrows()]
    return tabela


def teste_mesmo_mes(mesmo_mes):
    """Wilcoxon pareado por mês do ano: depois/antes."""
    pares = mesmo_mes.dropna(subset=["antes", "depois"])
    log_razao = np.log(pares.depois / pares.antes)
    teste = stats.wilcoxon(log_razao)
    return pd.Series({"meses": len(pares), "variação mediana": np.expm1(log_razao.median()),
                      "meses com aumento": int((log_razao > 0).sum()), "p (Wilcoxon, bilateral)": teste.pvalue},
                     name="mesmo mês: depois × antes")


def teste_duracao(con):
    """Mann-Whitney entre as durações antes e depois (amostra de até 20 mil registros por período)."""
    amostras = {}
    for periodo in ["1 antes", "2 depois"]:
        amostras[periodo] = con.sql(f"""
            SELECT duracao_h FROM micro
            WHERE nao_programada AND NOT duracao_suspeita AND duracao_h IS NOT NULL
              AND periodo_de(data) = '{periodo}'
            USING SAMPLE 20000 ROWS (reservoir, 42)
        """).df().duracao_h
    teste = stats.mannwhitneyu(amostras["2 depois"], amostras["1 antes"])
    # probabilidade de uma interrupção de depois durar mais que uma de antes (0,5 = iguais)
    prob = teste.statistic / (len(amostras["1 antes"]) * len(amostras["2 depois"]))
    return pd.Series({"P(depois dura mais que antes)": prob, "p (Mann-Whitney)": teste.pvalue},
                     name="duração: depois × antes")


def teste_clima_periodo(dias):
    """A sensibilidade a dias extremos mudou depois de ago/2023? (interação extremo × depois)."""
    dados = dias.loc[dias.esquema_2026.eq(0)]
    modelo = ajustar_nb("interrupcoes ~ extremo * depois + C(mes) + C(dia_semana) + feriado + tendencia", dados)
    nomes = modelo.params.index
    combinacao = np.zeros(len(nomes))
    combinacao[[nomes.get_loc("extremo"), nomes.get_loc("extremo:depois")]] = 1
    depois = modelo.t_test(combinacao)
    ic = np.asarray(depois.conf_int()).ravel()
    tabela = pd.DataFrame({
        "dia extremo · antes": razao(modelo, "extremo"),
        "dia extremo · depois": {"razão": np.exp(float(np.ravel(depois.effect)[0])), "IC95% inf": np.exp(ic[0]),
                                 "IC95% sup": np.exp(ic[1]), "p": float(np.ravel(depois.pvalue)[0])},
        "mudança (depois ÷ antes)": razao(modelo, "extremo:depois"),
    }).T
    return tabela


def teste_temperatura(dia_carga):
    """H1: termo quadrático da temperatura na carga de dias úteis, com o vértice da parábola."""
    d = dia_carga.query("n_ufs_feriado == 0 and dia_semana < 5").dropna(subset=["temp_media"]).copy()
    d = d.sort_values("data")
    d["ano"] = d.data.dt.year
    d["t"] = d.temp_media - 20
    modelo = smf.ols("np.log(carga_max) ~ t + I(t**2) + C(dia_semana) + C(ano)", d).fit(**HAC)
    quad = next(n for n in modelo.params.index if "**" in n)
    return pd.Series({"coef. T²": modelo.params[quad], "p T²": modelo.pvalues[quad],
                      "temperatura de menor carga (°C)": 20 - modelo.params["t"] / (2 * modelo.params[quad])},
                     name="H1 · carga × temperatura")


def teste_feriados(feriados):
    """H2: feriados nacionais reduzem a carga? Wilcoxon unilateral sobre log(feriado/referência)."""
    nacionais = feriados.loc[feriados.n_ufs_feriado.eq(3)]
    log_razao = np.log1p(nacionais.variacao)
    teste = stats.wilcoxon(log_razao, alternative="less")
    return pd.Series({"feriados nacionais": len(nacionais), "variação mediana": np.expm1(log_razao.median()),
                      "p (Wilcoxon, unilateral)": teste.pvalue}, name="H2 · feriados nacionais")
