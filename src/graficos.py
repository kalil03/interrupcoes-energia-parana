"""Gráficos da Etapa 3."""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .banco import PRIVATIZACAO

CORES = {"1 antes": "tab:blue", "2 depois": "tab:orange", "3 em 2026 (esquema novo)": "tab:gray"}
PRIV = pd.Timestamp(PRIVATIZACAO)

plt.rcParams.update({
    "figure.figsize": (10, 4), "figure.dpi": 110,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.3,
    "axes.titleweight": "bold", "legend.frameon": False,
})


def _privatizacao(eixo, rotulo=True):
    """Linha da privatização e fundo levemente sombreado no período anterior."""
    inicio, _ = eixo.get_xlim()
    priv = mdates.date2num(PRIV)
    eixo.axvspan(inicio, priv, color="tab:blue", alpha=0.05, lw=0)
    eixo.axvline(priv, color="tab:red", ls="--", lw=1.2, label="privatização (ago/2023)" if rotulo else None)
    eixo.set_xlim(left=inicio)


def _lacunas(eixo, mensal):
    """Faixa laranja nos meses sem cobertura completa da ANEEL."""
    for i, mes in enumerate(mensal.loc[mensal.dias_com_dados.lt(mensal.dias_no_mes), "mes"]):
        eixo.axvspan(mes, mes + pd.offsets.MonthEnd(1), color="tab:orange", alpha=0.2, lw=0,
                     label="mês sem dados completos" if i == 0 else None)


def interrupcoes_mensais(mensal):
    fig, eixos = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    for eixo, coluna, titulo, unidade in [
        (eixos[0], "interrupcoes_dia", "Interrupções não programadas da Copel", "interrupções/dia"),
        (eixos[1], "uc_horas_dia", "Consumidores × horas sem energia", "UC-horas/dia"),
    ]:
        eixo.plot(mensal.mes, mensal[coluna], marker="o", ms=3, lw=1, alpha=0.7, label="média do mês")
        if coluna == "interrupcoes_dia":
            eixo.plot(mensal.mes, mensal.media_movel_12m, lw=2.5, label="média móvel de 12 meses")
        _privatizacao(eixo, rotulo=coluna == "interrupcoes_dia")
        _lacunas(eixo, mensal)
        eixo.set(title=titulo, ylabel=unidade)
    eixos[0].legend(loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.show()


def antes_depois_por_mes(mesmo_mes):
    x = np.arange(len(mesmo_mes))
    fig, eixo = plt.subplots(figsize=(11, 4.2))
    eixo.bar(x - 0.2, mesmo_mes.antes, width=0.4, color=CORES["1 antes"], label="antes (jan/22–jul/23)")
    eixo.bar(x + 0.2, mesmo_mes.depois, width=0.4, color=CORES["2 depois"], label="depois (ago/23–dez/25)")
    for xi, (_, linha) in zip(x, mesmo_mes.iterrows()):
        if pd.notna(linha.variacao):
            topo = max(linha.antes, linha.depois)
            eixo.annotate(f"{linha.variacao:+.0%}", (xi, topo), xytext=(0, 4), textcoords="offset points",
                          ha="center", fontsize=8, color="tab:red" if linha.variacao > 0 else "tab:green")
    nomes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    eixo.set_xticks(x, [nomes[m - 1] for m in mesmo_mes.mes])
    eixo.set(ylabel="interrupções/dia", title="Mesmo mês do ano: antes × depois da privatização")
    eixo.set_ylim(top=eixo.get_ylim()[1] * 1.06)
    eixo.legend(loc="lower right", fontsize=8)
    plt.show()


def dec_fec(indicadores):
    fig, eixos = plt.subplots(1, 2, figsize=(12, 4))
    for eixo, coluna, titulo, unidade in [
        (eixos[0], "dec_12m", "DEC aproximado (12 meses)", "horas sem energia por consumidor"),
        (eixos[1], "fec_12m", "FEC aproximado (12 meses)", "interrupções por consumidor"),
    ]:
        eixo.plot(indicadores.mes, indicadores[coluna], marker="o", ms=3, lw=2)
        _privatizacao(eixo)
        eixo.set(title=titulo, ylabel=unidade)
        eixo.tick_params(axis="x", rotation=30)
    eixos[0].legend(fontsize=8)
    fig.suptitle("Indicadores de continuidade aproximados · interrupções não programadas", y=1.02)
    plt.tight_layout()
    plt.show()


def causas(tabela):
    colunas = [c for c in ["1 antes", "2 depois"] if c in tabela]
    y = np.arange(len(tabela))
    fig, eixo = plt.subplots(figsize=(10, 0.45 * len(tabela) + 1.8))
    for i, coluna in enumerate(colunas):
        eixo.barh(y + (i - 0.5) * 0.4, tabela[coluna], height=0.4, color=CORES[coluna], label=coluna[2:])
    if len(colunas) == 2:
        variacao = tabela[colunas[1]] / tabela[colunas[0]] - 1
        for yi, (valor, v) in enumerate(zip(tabela[colunas].max(axis=1), variacao)):
            eixo.annotate(f"{v:+.0%}", (valor, yi), xytext=(4, 0), textcoords="offset points", va="center",
                          fontsize=8, color="tab:red" if v > 0 else "tab:green")
    eixo.set_yticks(y, tabela.index)
    eixo.set(xlabel="registros por dia", title="Causas das interrupções não programadas (2022–2025)")
    eixo.set_xlim(right=eixo.get_xlim()[1] * 1.1)
    eixo.legend(fontsize=8, loc="lower right")
    plt.show()


def duracao(tabela):
    x = np.arange(len(tabela))
    fig, eixos = plt.subplots(1, 2, figsize=(11, 3.8))
    cores = [CORES.get(p, "tab:gray") for p in tabela.periodo]
    rotulos = [p[2:] for p in tabela.periodo]
    eixos[0].bar(x, tabela.mediana_h * 60, color=cores)
    eixos[0].set(title="Duração mediana", ylabel="minutos")
    eixos[1].bar(x - 0.2, tabela.frac_mais_3h * 100, width=0.4, color=cores, label="> 3 h")
    eixos[1].bar(x + 0.2, tabela.frac_mais_24h * 100, width=0.4, color=cores, alpha=0.45, hatch="//", label="> 24 h")
    eixos[1].set(title="Interrupções longas", ylabel="% das interrupções")
    eixos[1].legend(fontsize=8)
    for eixo in eixos:
        eixo.set_xticks(x, rotulos, fontsize=8)
    plt.tight_layout()
    plt.show()


def razoes(tabela, titulo, margem=0.10):
    y = np.arange(len(tabela))[::-1]
    fig, eixo = plt.subplots(figsize=(9, 0.55 * len(tabela) + 1.6))
    eixo.axvspan(1 - margem, 1 + margem, color="tab:green", alpha=0.08, lw=0,
                 label=f"diferença pequena (±{margem:.0%})")
    eixo.axvline(1, color="black", lw=1)
    cores = ["tab:red" if p < 0.05 and r > 1 else "tab:green" if p < 0.05 else "tab:gray"
             for r, p in zip(tabela["razão"], tabela["p"])]
    for yi, (_, linha), cor in zip(y, tabela.iterrows(), cores):
        eixo.errorbar(linha["razão"], yi, xerr=[[linha["razão"] - linha["IC95% inf"]], [linha["IC95% sup"] - linha["razão"]]],
                      fmt="o", color=cor, capsize=4, ms=6)
        eixo.annotate(f"{linha['razão']:.2f}", (linha["IC95% sup"], yi), xytext=(6, 0), textcoords="offset points",
                      va="center", fontsize=8)
    eixo.set_yticks(y, tabela.index, fontsize=9)
    eixo.set(xlabel="razão (1 = sem mudança) · IC 95%", title=titulo)
    eixo.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    plt.show()


def carga_temperatura(faixas):
    centro = faixas.faixa_inicio + 1
    fig, eixo = plt.subplots(figsize=(8, 4))
    eixo.plot(centro, faixas.carga_relativa, marker="o", ms=7, lw=2)
    minimo = faixas.loc[faixas.carga_relativa.idxmin()]
    eixo.axvline(minimo.faixa_inicio + 1, color="tab:red", ls="--", lw=1,
                 label=f"menor carga: {minimo.faixa_inicio:.0f}–{minimo.faixa_inicio + 2:.0f} °C")
    eixo.axhline(1, color="black", lw=0.8)
    for x, v, n in zip(centro, faixas.carga_relativa, faixas.dias):
        eixo.annotate(f"n={n}", (x, v), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=7, color="gray")
    eixo.set(xlabel="temperatura média do PR (°C)", ylabel="carga máxima / média do ano",
             title="H1 · Carga do Sul por faixa de temperatura (dias úteis)")
    eixo.legend(fontsize=8)
    plt.show()
