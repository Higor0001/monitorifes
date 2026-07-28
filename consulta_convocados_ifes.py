#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script de Consulta e Monitoramento Full-Time - IFES Campus Cachoeiro de Itapemirim
Monitora continuamente a página do edital e notifica em tempo real sobre novas convocações, 
alterações no cronograma ou novos documentos publicados.
"""

import sys
import os
import ssl
import json
import csv
import re
import time
import argparse
import datetime
import urllib.request
import urllib.parse
import hashlib

from bs4 import BeautifulSoup
import fitz  # PyMuPDF

# Configurar encoding UTF-8 para o terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Suprimir mensagens internas do PyMuPDF
try:
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass

URL_EDITAL_PADRAO = "https://cachoeiro.ifes.edu.br/processosseletivos/alunos/17163-edital-19-2026-chamada-publica-de-oferta-de-vagas-dos-cursos-tecnicos-concomitante-e-subsequente"
ARQUIVO_ESTADO = "estado_monitor.json"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch_page_html(url):
    """Requisita o HTML completo da página do edital."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, context=ctx) as response:
        return response.read().decode('utf-8', errors='ignore')

def download_file(url):
    """Baixa arquivos (PDFs) tratando caracteres especiais de URL."""
    parsed = urllib.parse.urlparse(url)
    safe_path = urllib.parse.quote(parsed.path)
    safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, parsed.fragment))
    req = urllib.request.Request(safe_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, context=ctx) as response:
        return response.read()

def enviar_notificacao_webhook(webhook_url, mensagem):
    """Envia notificação via Webhook (Discord / Slack / Telegram)."""
    if not webhook_url:
        return
    try:
        data = json.dumps({"content": mensagem, "text": mensagem}).encode('utf-8')
        req = urllib.request.Request(webhook_url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx) as resp:
            pass
        print(f"[🔔 Webhook] Notificação enviada com sucesso!")
    except Exception as e:
        print(f"[-] Erro ao enviar webhook: {e}", file=sys.stderr)

def parse_cronograma(soup):
    """Extrai o Cronograma de Atividades da página."""
    cronograma = []
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue
        headers = [th.get_text(strip=True).upper() for th in rows[0].find_all(['th', 'td'])]
        if any('ATIVIDADE' in h for h in headers) or any('DATA' in h for h in headers) or any('ETAPA' in h for h in headers):
            for row in rows[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                if len(cols) >= 2:
                    cronograma.append({
                        'atividade': cols[0],
                        'data': cols[1]
                    })
    return cronograma

def parse_quadro_vagas(soup):
    """Extrai a tabela com o Quadro de Vagas."""
    vagas = []
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue
        headers = [th.get_text(strip=True).upper() for th in rows[0].find_all(['th', 'td'])]
        if any('CURSO' in h for h in headers) and any('VAGAS' in h for h in headers):
            for row in rows[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                if len(cols) >= 4:
                    vagas.append({
                        'curso': cols[0],
                        'turno': cols[1],
                        'duracao': cols[2],
                        'vagas': cols[3]
                    })
    return vagas

def parse_documentos_e_links(soup, base_url):
    """Extrai publicações, links de editais, formulários e resultados."""
    documentos = []
    main_content = soup.find('div', class_='itemBody') or soup.find('div', id='content') or soup
    
    for a in main_content.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        full_url = urllib.parse.urljoin(base_url, href)
        
        if any(ext in href.lower() for ext in ['.pdf', 'forms.gle', 'gedoc', 'documento']) or \
           any(kw in text.upper() for kw in ['EDITAL', 'INSCRIÇÃO', 'RESULTADO', 'CONVOCAÇÃO', 'MATRÍCULA', 'ELETROMECÂNICA', 'INFORMÁTICA', 'MINERAÇÃO']):
            if text or full_url:
                documentos.append({
                    'titulo': text if text else "Documento Anexo",
                    'url': full_url
                })
    return documentos

def parse_pdf_candidates(pdf_bytes, document_label):
    """Extrai candidatos do PDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    candidates = []
    course_name = document_label

    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"

    if "DO CRONOGRAMA:" in full_text.upper() or "DAS DISPOSIÇÕES GERAIS" in full_text.upper() or "DA INSCRIÇÃO:" in full_text.upper():
        return course_name, []

    lines = [line.strip() for line in full_text.splitlines() if line.strip()]

    for line in lines:
        if "CURSO TÉCNICO" in line.upper() or "CURSO:" in line.upper():
            course_name = line.replace("Curso:", "").strip()
            break

    is_document_convocacao = any(kw in full_text.upper() for kw in ['CONVOCADOS PARA MATRÍCULA', 'CONVOCAÇÃO PARA MATRÍCULA', 'RESULTADO E CONVOCAÇÃO'])

    extracted_from_tables = False
    for page in doc:
        try:
            tabs = page.find_tables()
            if tabs and tabs.tables:
                for t in tabs.tables:
                    rows = t.extract()
                    for row in rows:
                        if not row:
                            continue
                        clean_row = [str(cell or '').strip() for cell in row if str(cell or '').strip()]
                        if len(clean_row) < 2:
                            continue
                        
                        col_0 = clean_row[0]
                        col_1 = clean_row[1]
                        col_2 = clean_row[2] if len(clean_row) >= 3 else ("Convocado" if is_document_convocacao else "Classificado")

                        if 'CLASSIFICA' in col_0.upper() or 'NOME' in col_1.upper():
                            continue

                        m_rank = re.match(r'^(\d+)[\º\ª\.]?$', col_0)
                        if m_rank and col_1 and not any(kw in col_1.lower() for kw in ['inscrição:', 'pré-requisitos:', 'resultado:', 'cronograma:', 'disposições']):
                            candidates.append({
                                'posicao': m_rank.group(1),
                                'nome': col_1,
                                'situacao': col_2,
                                'curso': course_name,
                                'documento': document_label
                            })
                            extracted_from_tables = True
        except Exception:
            pass

    if not extracted_from_tables or len(candidates) == 0:
        i = 0
        while i < len(lines):
            line = lines[i]
            m = re.match(r'^(\d+)[\º\ª\.]?$', line)
            if m and i + 1 < len(lines):
                rank = m.group(1)
                name = lines[i + 1]
                
                status = "Convocado" if is_document_convocacao else "Classificado"
                if i + 2 < len(lines):
                    next_line = lines[i + 2]
                    valid_statuses = ['CLASSIFICADO', 'SUPLENTE', 'CONVOCADO', 'MATRICULADO', 'DESCLASSIFICADO']
                    if any(s in next_line.upper() for s in valid_statuses):
                        status = next_line
                        i += 3
                    else:
                        i += 2
                else:
                    i += 2

                if not name.isdigit() and len(name) > 2 and 'CLASSIFICA' not in name.upper() and not any(kw in name.lower() for kw in ['inscrição:', 'pré-requisitos:', 'resultado:', 'cronograma:', 'disposições']):
                    candidates.append({
                        'posicao': rank,
                        'nome': name,
                        'situacao': status,
                        'curso': course_name,
                        'documento': document_label
                    })
                    continue
            i += 1

    return course_name, candidates

def consultar_edital_completo(url=URL_EDITAL_PADRAO, apenas_convocados=True, filtro_curso=None):
    """Executa a varredura da URL informada."""
    html = fetch_page_html(url)
    soup = BeautifulSoup(html, 'html.parser')

    main_content = soup.find('div', class_='itemBody') or soup.find('div', id='content') or soup

    titulo_edital = "Processo Seletivo IFES"
    if soup.find('h2', class_='itemTitle') or soup.find('h1'):
        t_elem = soup.find('h2', class_='itemTitle') or soup.find('h1')
        titulo_edital = t_elem.get_text(strip=True)

    quadro_vagas = parse_quadro_vagas(main_content)
    cronograma = parse_cronograma(main_content)
    documentos = parse_documentos_e_links(main_content, base_url=url)

    pdf_links = []
    for doc in documentos:
        u_lower = doc['url'].lower()
        t_lower = doc['titulo'].lower()
        if '.pdf' in u_lower:
            if any(kw in u_lower or kw in t_lower for kw in ['resultado', 'convoca', 'inscrito', 'eletromecanica', 'informática', 'mineracao', 'mineração']):
                pdf_links.append(doc)
            elif 'edital' in u_lower and 'resultado' not in u_lower and 'convoca' not in u_lower:
                continue
            else:
                pdf_links.append(doc)
    
    candidatos_totais = []
    for doc_info in pdf_links:
        try:
            pdf_bytes = download_file(doc_info['url'])
            course_name, candidates = parse_pdf_candidates(pdf_bytes, doc_info['titulo'])

            if filtro_curso and filtro_curso.lower() not in course_name.lower() and filtro_curso.lower() not in doc_info['titulo'].lower():
                continue

            for c in candidates:
                status_upper = c['situacao'].upper()
                is_convocado = any(kw in status_upper for kw in ['CLASSIFICADO', 'CONVOCADO', 'MATRICULADO'])
                
                if apenas_convocados and not is_convocado:
                    continue

                candidatos_totais.append(c)
        except Exception as e:
            print(f"[-] Erro ao processar arquivo {doc_info['titulo']}: {e}", file=sys.stderr)

    contato_info = {
        'telefone': '(28) 3526-9021',
        'email_matricula': 'matricula.cai@ifes.edu.br',
        'email_processo': 'pstecnico.cai@ifes.edu.br'
    }

    return {
        'titulo': titulo_edital,
        'url': url,
        'data_consulta': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'quadro_vagas': quadro_vagas,
        'cronograma': cronograma,
        'documentos': documentos,
        'candidatos': candidatos_totais,
        'contato': contato_info
    }

def exibir_relatorio(dados, mostrar_cronograma=True, mostrar_vagas=True, mostrar_candidatos=True):
    """Exibe o relatório formatado no terminal."""
    print("\n" + "=" * 85)
    print(f"  {dados['titulo'].upper()}")
    print(f"  URL: {dados['url']}")
    print(f"  Data da Consulta: {dados['data_consulta']}")
    print("=" * 85)

    if mostrar_vagas and dados['quadro_vagas']:
        print("\n📌 QUADRO DE VAGAS OFERTADAS:")
        print("-" * 85)
        print(f"{'CURSO':<40} | {'TURNO':<10} | {'DURAÇÃO':<10} | {'VAGAS':<6}")
        print("-" * 85)
        for v in dados['quadro_vagas']:
            print(f"{v['curso']:<40} | {v['turno']:<10} | {v['duracao']:<10} | {v['vagas']:<6}")

    if mostrar_cronograma and dados['cronograma']:
        print("\n📅 CRONOGRAMA DE ATIVIDADES DO EDITAL:")
        print("-" * 85)
        print(f"{'ATIVIDADE / ETAPA':<55} | {'DATA / PERÍODO':<25}")
        print("-" * 85)
        for item in dados['cronograma']:
            print(f"{item['atividade']:<55} | {item['data']:<25}")

    if dados['documentos']:
        print("\n🔗 DOCUMENTOS E PUBLICAÇÕES OFICIAIS:")
        print("-" * 85)
        for doc in dados['documentos']:
            print(f" • {doc['titulo']:<45} -> {doc['url']}")

    if mostrar_candidatos:
        candidatos = dados['candidatos']
        if not candidatos:
            print("\n⚠️ Nenhum candidato encontrado para os critérios selecionados.")
        else:
            cursos = {}
            for c in candidatos:
                curso = c['curso']
                if curso not in cursos:
                    cursos[curso] = []
                cursos[curso].append(c)

            print("\n🎓 LISTA DE CONVOCADOS / CLASSIFICADOS PARA MATRÍCULA:")
            total = 0
            for curso, lista in cursos.items():
                print("\n" + "-" * 85)
                print(f"   {curso.upper()} ({len(lista)} candidatos)")
                print("-" * 85)
                print(f"{'POS.':<6} | {'NOME DO CANDIDATO':<48} | {'SITUAÇÃO':<20}")
                print("-" * 85)
                for item in lista:
                    print(f"{item['posicao']:<6} | {item['nome']:<48} | {item['situacao']:<20}")
                    total += 1

            print("\n" + "=" * 85)
            print(f" TOTAL DE CANDIDATOS LISTADOS: {total}")
            print("=" * 85)

    print("\n✉️ CONTATO PARA DÚVIDAS E RECURSOS:")
    print(f" • Telefone: {dados['contato']['telefone']}")
    print(f" • E-mail Matrícula: {dados['contato']['email_matricula']}")
    print(f" • E-mail Processo Seletivo: {dados['contato']['email_processo']}\n")

def executar_modo_monitor(url, intervalo_segundos=300, webhook_url=None):
    """Executa o monitoramento contínuo (Full-Time) da página."""
    print("=" * 85)
    print(" 🚀 INICIANDO MONITORAMENTO FULL-TIME DO EDITAL IFES")
    print(f" 🌐 URL: {url}")
    print(f" ⏱️ Intervalo de checagem: {intervalo_segundos} segundos ({intervalo_segundos//60} minutos)")
    if webhook_url:
        print(f" 🔔 Webhook ativo para notificações instantâneas.")
    print("=" * 85 + "\n")

    estado_anterior = None
    if os.path.exists(ARQUIVO_ESTADO):
        try:
            with open(ARQUIVO_ESTADO, 'r', encoding='utf-8') as f:
                estado_anterior = json.load(f)
            print(f"[i] Estado anterior carregado de '{ARQUIVO_ESTADO}'.")
        except Exception:
            pass

    ciclo = 1
    while True:
        horario = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{horario}] 🔍 Verificando atualização (Ciclo #{ciclo})...")
        
        try:
            dados_atuais = consultar_edital_completo(url=url, apenas_convocados=True)
            
            # Gerar hash do estado atual (documentos + candidatos)
            resumo_estado = {
                'documentos': [d['url'] for d in dados_atuais['documentos']],
                'total_candidatos': len(dados_atuais['candidatos']),
                'candidatos': [f"{c['posicao']}-{c['nome']}-{c['situacao']}" for c in dados_atuais['candidatos']]
            }
            hash_atual = hashlib.md5(json.dumps(resumo_estado, sort_keys=True).encode('utf-8')).hexdigest()

            if estado_anterior is None:
                print(f"[{horario}] ✅ Monitor inicializado. {len(dados_atuais['documentos'])} documentos e {len(dados_atuais['candidatos'])} convocados rastreados.")
                estado_anterior = {'hash': hash_atual, 'dados': dados_atuais}
                with open(ARQUIVO_ESTADO, 'w', encoding='utf-8') as f:
                    json.dump(estado_anterior, f, ensure_ascii=False, indent=2)

            elif estado_anterior.get('hash') != hash_atual:
                msg_alerta = f"🚨 ATUALIZAÇÃO DETECTADA NO EDITAL IFES!\nData: {horario}\nTotal Convocados: {len(dados_atuais['candidatos'])}\nURL: {url}"
                print("\n" + "!" * 85)
                print(f"  {msg_alerta}")
                print("!" * 85 + "\n")
                
                exibir_relatorio(dados_atuais)
                enviar_notificacao_webhook(webhook_url, msg_alerta)

                estado_anterior = {'hash': hash_atual, 'dados': dados_atuais}
                with open(ARQUIVO_ESTADO, 'w', encoding='utf-8') as f:
                    json.dump(estado_anterior, f, ensure_ascii=False, indent=2)
            else:
                print(f"[{horario}] 💤 Nenhuma alteração detectada. Aguardando próximo ciclo...")

        except Exception as e:
            print(f"[{horario}] ⚠️ Erro durante checagem de ciclo: {e}", file=sys.stderr)

        ciclo += 1
        time.sleep(intervalo_segundos)

def main():
    parser = argparse.ArgumentParser(description="Consulta e Monitoramento Full-Time IFES Cachoeiro")
    parser.add_argument("--url", type=str, default=URL_EDITAL_PADRAO, help="URL completa do Edital no portal IFES")
    parser.add_argument("--monitor", action="store_true", help="Ativa o modo de monitoramento contínuo (Full-Time)")
    parser.add_argument("--intervalo", type=int, default=300, help="Intervalo em segundos entre verificações (Padrão: 300s / 5min)")
    parser.add_argument("--webhook", type=str, help="URL de Webhook para enviar notificações (Discord / Slack / Telegram)")
    
    parser.add_argument("--cronograma", action="store_true", help="Exibe apenas o cronograma do edital")
    parser.add_argument("--convocados", action="store_true", help="Exibe apenas a lista de convocados")
    parser.add_argument("--todos", action="store_true", help="Inclui suplentes e desclassificados na lista de candidatos")
    parser.add_argument("--curso", type=str, help="Filtra resultados por nome do curso")
    parser.add_argument("--json", type=str, help="Exporta o resultado completo para um arquivo JSON")
    parser.add_argument("--csv", type=str, help="Exporta a lista de candidatos para um arquivo CSV")

    args = parser.parse_args()

    if args.monitor:
        executar_modo_monitor(url=args.url, intervalo_segundos=args.intervalo, webhook_url=args.webhook)
    else:
        apenas_convocados = not args.todos
        dados = consultar_edital_completo(url=args.url, apenas_convocados=apenas_convocados, filtro_curso=args.curso)

        mostrar_cronograma = True
        mostrar_vagas = True
        mostrar_candidatos = True

        if args.cronograma:
            mostrar_candidatos = False
        elif args.convocados:
            mostrar_cronograma = False
            mostrar_vagas = False

        exibir_relatorio(dados, mostrar_cronograma=mostrar_cronograma, mostrar_vagas=mostrar_vagas, mostrar_candidatos=mostrar_candidatos)

        if args.json:
            with open(args.json, 'w', encoding='utf-8') as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            print(f"[+] Dados completos exportados para JSON em: {args.json}")

        if args.csv:
            with open(args.csv, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['curso', 'posicao', 'nome', 'situacao', 'documento'])
                writer.writeheader()
                writer.writerows(dados['candidatos'])
            print(f"[+] Lista de candidatos exportada para CSV em: {args.csv}")

if __name__ == "__main__":
    main()
