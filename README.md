# 🎓 Monitor IFES - Consulta e Notificação de Convocados (Campus Cachoeiro)

Script de consulta e monitoramento em tempo real do **Edital 19/2026** (Chamada Pública de Oferta de Vagas dos Cursos Técnicos Concomitantes e Subsequentes) do **IFES Campus Cachoeiro de Itapemirim**.

---

## 🌟 Recursos

- 📌 **Quadro de Vagas**: Extrai vagas ofertadas por curso (Informática para Internet, Eletromecânica, Mineração).
- 📅 **Cronograma Oficial**: Rastreia datas de inscrições, recursos, convocações e matrículas.
- 🎓 **Leitura de PDFs com PyMuPDF**: Baixa os PDFs de listas preliminares/finais e extrai os nomes e posições dos candidatos classificados.
- 🔔 **Modo Monitor (Full-Time)**: Executa verificações periódicas e envia alertas via Webhook (Telegram, Discord, Slack) sempre que um novo edital ou resultado for publicado.

---

## 🚀 Como Executar

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 2. Consulta Única no Terminal

```bash
python consulta_convocados_ifes.py
```

### 3. Modo Monitoramento Contínuo (Full-Time)

Para rodar o monitor a cada 5 minutos (300s) e receber alertas por Webhook:

```bash
python consulta_convocados_ifes.py --monitor --intervalo 300 --webhook "https://seu-webhook-url"
```

---

## 📄 Opções de Comando

| Opção | Descrição |
| :--- | :--- |
| `--monitor` | Ativa o modo de monitoramento contínuo |
| `--intervalo 300` | Define o tempo entre verificações (em segundos) |
| `--webhook URL` | URL do Webhook para receber alertas instantâneos |
| `--curso "Informática"` | Filtra a exibição para um curso específico |
| `--json resultado.json` | Exporta a consulta para um arquivo JSON |
| `--csv resultado.csv` | Exporta a lista de convocados para CSV |
