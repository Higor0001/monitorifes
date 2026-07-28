/**
 * Cloudflare Worker - Monitor Full-Time IFES Cachoeiro
 * 
 * Agendamento: 08:00, 12:00, 14:00, 17:00, 18:00, 20:00, 23:00 (Horário de Brasília)
 * Suporte a Telegram Webhook (Responde instantaneamente a qualquer mensagem enviada para o bot no Telegram)
 */

import { extractText } from 'unpdf';

const URL_EDITAL_PADRAO = "https://cachoeiro.ifes.edu.br/processosseletivos/alunos/17163-edital-19-2026-chamada-publica-de-oferta-de-vagas-dos-cursos-tecnicos-concomitante-e-subsequente";

let estadoGlobalMemoria = null;

export default {
  // Executado nos 7 horários fixos configurados (8h, 12h, 14h, 17h, 18h, 20h, 23h)
  async scheduled(event, env, ctx) {
    ctx.waitUntil(verificarEditalEEnviarResultados(env, false, true));
  },

  // Executado via HTTP GET ou Telegram Webhook (POST) quando o usuário envia mensagem no Telegram
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const workerUrl = `${url.protocol}//${url.host}`;

    // 1. Se for mensagem recebida via TELEGRAM WEBHOOK (POST)
    if (request.method === "POST") {
      try {
        const update = await request.json();
        if (update && update.message && update.message.chat) {
          const chatId = update.message.chat.id;
          ctx.waitUntil(verificarEditalEEnviarResultados(env, true, true, workerUrl, chatId));
        }
      } catch (e) {
        console.error("Erro no webhook do Telegram:", e);
      }
      return new Response("OK", { status: 200 });
    }

    // 2. Se for acesso via navegador HTTP GET ou rota de registrar webhook (?setup_webhook=true)
    if (url.searchParams.get("setup_webhook") === "true") {
      const token = env.TELEGRAM_TOKEN || "8928855109:AAGU-Pa-6btwGYN2qVZhqbQ7M3pO9-aGKnU";
      const webhookRes = await fetch(`https://api.telegram.org/bot${token}/setWebhook?url=${workerUrl}`);
      const webhookJson = await webhookRes.json();
      return new Response(JSON.stringify(webhookJson, null, 2), {
        headers: { "Content-Type": "application/json" }
      });
    }

    // Acesso normal HTTP GET -> envia relatório e retorna JSON
    const resultado = await verificarEditalEEnviarResultados(env, true, true, workerUrl);
    return new Response(JSON.stringify(resultado, null, 2), {
      headers: { "Content-Type": "application/json; charset=utf-8" }
    });
  }
};

function decodeHtmlEntities(str) {
  if (!str) return '';
  return str
    .replace(/&aacute;/g, 'á').replace(/&Aacute;/g, 'Á')
    .replace(/&eacute;/g, 'é').replace(/&Eacute;/g, 'É')
    .replace(/&iacute;/g, 'í').replace(/&Iacute;/g, 'Í')
    .replace(/&o-acute;/g, 'ó').replace(/&oacute;/g, 'ó').replace(/&Oacute;/g, 'Ó')
    .replace(/&uacute;/g, 'ú').replace(/&Uacute;/g, 'Ú')
    .replace(/&atilde;/g, 'ã').replace(/&Atilde;/g, 'Ã')
    .replace(/&otilde;/g, 'õ').replace(/&Otilde;/g, 'Õ')
    .replace(/&ccedil;/g, 'ç').replace(/&Ccedil;/g, 'Ç')
    .replace(/&ordf;/g, 'ª').replace(/&ordm;/g, 'º')
    .replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ');
}

function extrairMetadados(html) {
  const matchMod = html.match(/Última atualização em (.*?)</i);
  const matchPub = html.match(/Publicado:\s*(.*?)</i);
  return {
    modificado: matchMod ? decodeHtmlEntities(matchMod[1].trim()) : "Não informado",
    publicado: matchPub ? decodeHtmlEntities(matchPub[1].trim()) : "Não informado"
  };
}

function extrairCronograma(html) {
  const cronograma = [];
  const tableRegex = /<table[\s\S]*?<\/table>/gi;
  let match;
  while ((match = tableRegex.exec(html)) !== null) {
    const tableHtml = match[0];
    if (tableHtml.toLowerCase().includes("atividade") || tableHtml.toLowerCase().includes("convocação") || tableHtml.toLowerCase().includes("inscrição")) {
      const trRegex = /<tr[\s\S]*?<\/tr>/gi;
      let trMatch;
      while ((trMatch = trRegex.exec(tableHtml)) !== null) {
        const rowHtml = trMatch[0];
        const cells = [...rowHtml.matchAll(/<td[\s\S]*?<\/td>/gi)].map(m => {
          const raw = m[0].replace(/<[^>]+>/g, '');
          return decodeHtmlEntities(raw).replace(/\s+/g, ' ').trim();
        }).filter(Boolean);

        if (cells.length >= 2) {
          const atividade = cells[0];
          const data = cells[1];
          if (!atividade.toLowerCase().includes("atividade") && !data.toLowerCase().includes("data")) {
            cronograma.push({ atividade, data });
          }
        }
      }
    }
  }
  return cronograma;
}

function extrairLinksDocumentos(html, baseUrl) {
  const hrefRegex = /href=["']([^"']+)["']/gi;
  const links = [];
  let m;
  while ((m = hrefRegex.exec(html)) !== null) {
    let rawLink = m[1];
    if (!rawLink.startsWith("http")) {
      try {
        rawLink = new URL(rawLink, baseUrl).href;
      } catch (e) {}
    }
    const dec = decodeURIComponent(rawLink).toLowerCase();
    if ((dec.includes(".pdf") || dec.includes("gedoc") || dec.includes("documento")) && !links.includes(rawLink)) {
      links.push(rawLink);
    }
  }
  return links;
}

async function extrairCandidatosDoPDF(pdfBytes, nomeDoc) {
  try {
    const uint8Data = new Uint8Array(pdfBytes);
    const pdfResult = await extractText(uint8Data);
    
    let fullText = "";
    if (pdfResult && pdfResult.text) {
      fullText = Array.isArray(pdfResult.text) ? pdfResult.text.join("\n") : pdfResult.text;
    }

    if (fullText.includes("DO CRONOGRAMA:") || fullText.includes("DAS DISPOSIÇÕES GERAIS")) {
      return { curso: nomeDoc, candidatos: [] };
    }

    const lines = fullText.split("\n").map(l => l.trim()).filter(Boolean);

    let curso = nomeDoc;
    for (const l of lines) {
      if (l.toUpperCase().includes("CURSO TÉCNICO") || l.toUpperCase().includes("CURSO:")) {
        curso = l.replace(/Curso:/i, "").trim();
        break;
      }
    }

    const candidatos = [];
    const isConvocacao = fullText.toUpperCase().includes("CONVOCADOS PARA MATRÍCULA") || fullText.toUpperCase().includes("CONVOCAÇÃO PARA MATRÍCULA");

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      const matchSingleLine = line.match(/^(\d+)[\º\ª\.]?\s+(.*?)\s+(Classificado|Suplente|Convocado|Matriculado|Desclassificado)$/i);
      if (matchSingleLine) {
        candidatos.push({
          posicao: matchSingleLine[1],
          nome: matchSingleLine[2].trim(),
          situacao: matchSingleLine[3].trim(),
          curso: curso
        });
        continue;
      }

      const mRank = line.match(/^(\d+)[\º\ª\.]?$/);
      if (mRank && i + 1 < lines.length) {
        const rank = mRank[1];
        const name = lines[i + 1];
        let status = isConvocacao ? "Convocado" : "Classificado";
        if (i + 2 < lines.length && ["CLASSIFICADO", "SUPLENTE", "CONVOCADO", "MATRICULADO"].some(s => lines[i + 2].toUpperCase().includes(s))) {
          status = lines[i + 2];
        }
        if (name && !/^\d+$/.test(name) && !name.toUpperCase().includes("CLASSIFICA")) {
          candidatos.push({ posicao: rank, nome: name, situacao: status, curso: curso });
        }
      }
    }

    return { curso, candidatos };
  } catch (err) {
    console.error("Erro ao analisar PDF com unpdf:", err);
    return { curso: nomeDoc, candidatos: [] };
  }
}

async function carregarEstadoSalvo(env) {
  if (env.STATE_KV) {
    try {
      const raw = await env.STATE_KV.get("ESTADO_EDITAL_IFES");
      if (raw) return JSON.parse(raw);
    } catch (e) {
      console.error("Erro lendo do KV:", e);
    }
  }
  return estadoGlobalMemoria;
}

async function salvarEstado(env, estado) {
  estadoGlobalMemoria = estado;
  if (env.STATE_KV) {
    try {
      await env.STATE_KV.put("ESTADO_EDITAL_IFES", JSON.stringify(estado));
    } catch (e) {
      console.error("Erro salvando no KV:", e);
    }
  }
}

function compararEstados(antigo, novo) {
  if (!antigo) return { temMudanca: true, primeiraExecucao: true };

  const mudancas = {
    temMudanca: false,
    primeiraExecucao: false,
    modificacaoDataMudou: false,
    modificacaoAnterior: antigo.meta.modificado,
    modificacaoNova: novo.meta.modificado,
    cronogramaMudou: [],
    novosLinks: [],
    convocadosMudaram: false
  };

  if (antigo.meta.modificado !== novo.meta.modificado) {
    mudancas.modificacaoDataMudou = true;
    mudancas.temMudanca = true;
  }

  for (let i = 0; i < novo.cronograma.length; i++) {
    const itemNovo = novo.cronograma[i];
    const itemAntigo = antigo.cronograma[i];

    if (!itemAntigo) {
      mudancas.cronogramaMudou.push(`➕ Novo evento inserido: [${itemNovo.atividade}] -> ${itemNovo.data}`);
      mudancas.temMudanca = true;
    } else if (itemAntigo.atividade !== itemNovo.atividade || itemAntigo.data !== itemNovo.data) {
      mudancas.cronogramaMudou.push(`✏️ Data/Evento alterado: [${itemNovo.atividade}] de '${itemAntigo.data}' para '${itemNovo.data}'`);
      mudancas.temMudanca = true;
    }
  }

  const linksAntigos = new Set(antigo.links);
  for (const link of novo.links) {
    if (!linksAntigos.has(link)) {
      mudancas.novosLinks.push(link);
      mudancas.temMudanca = true;
    }
  }

  if (antigo.totalConvocados !== novo.totalConvocados) {
    mudancas.convocadosMudaram = true;
    mudancas.temMudanca = true;
  }

  return mudancas;
}

async function verificarEditalEEnviarResultados(env, manualTest = false, forceReset = false, workerUrl = "", overrideChatId = null) {
  const targetUrl = env.URL_EDITAL || URL_EDITAL_PADRAO;
  console.log(`Checando edital no IFES: ${targetUrl}`);

  try {
    const resp = await fetch(targetUrl, {
      headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }
    });

    if (!resp.ok) throw new Error(`Erro HTTP ${resp.status}`);
    const html = await resp.text();

    const meta = extrairMetadados(html);
    const cronograma = extrairCronograma(html);
    const linksDocumentos = extrairLinksDocumentos(html, targetUrl);

    const pdfsParaAnalisar = linksDocumentos.filter(url => {
      const u = decodeURIComponent(url).toLowerCase();
      return u.includes(".pdf") && !u.includes("portaria_n") && !u.includes("documentos_necess");
    });

    const relatorioCursos = [];
    let totalConvocados = 0;

    for (const pdfUrl of pdfsParaAnalisar) {
      try {
        const pdfResp = await fetch(pdfUrl, { headers: { "User-Agent": "Mozilla/5.0" } });
        if (pdfResp.ok) {
          const pdfBuffer = await pdfResp.arrayBuffer();
          let nomeDoc = decodeURIComponent(pdfUrl.split('/').pop().replace('.pdf', ''));
          nomeDoc = nomeDoc.replace(/resultado_preliminar_-_/gi, '').replace(/Resultado_PS_\d+-\d+_Chamada_Pública_/gi, '');
          
          const resultado = await extrairCandidatosDoPDF(pdfBuffer, nomeDoc);
          
          const convocados = resultado.candidatos.filter(c => 
            ["CLASSIFICADO", "CONVOCADO", "MATRICULADO"].some(kw => c.situacao.toUpperCase().includes(kw))
          );

          if (convocados.length > 0) {
            relatorioCursos.push({ curso: resultado.curso, convocados });
            totalConvocados += convocados.length;
          }
        }
      } catch (e) {
        console.error(`Erro no PDF ${pdfUrl}:`, e);
      }
    }

    const estadoAtual = {
      meta,
      cronograma,
      links: linksDocumentos,
      cursos: relatorioCursos,
      totalConvocados,
      timestamp: new Date().toISOString()
    };

    const estadoAnterior = forceReset ? null : await carregarEstadoSalvo(env);
    const diff = compararEstados(estadoAnterior, estadoAtual);

    let mensagensTelegram = [];

    if (diff.primeiraExecucao || forceReset) {
      let msgAtual = `📌 <b>RELATÓRIO DO EDITAL IFES CACHOEIRO</b>\n`;
      msgAtual += `<b>Edital:</b> <a href="${targetUrl}">Chamada Pública IFES Edital 19/2026</a>\n`;
      msgAtual += `🕒 <b>Última Atualização no Site:</b> ${meta.modificado}\n\n`;

      msgAtual += `📅 <b>QUADRO DE DATAS (CRONOGRAMA MONITORADO):</b>\n`;
      for (const item of cronograma) {
        msgAtual += `  • <b>${item.atividade}:</b> ${item.data}\n`;
      }
      msgAtual += `\n`;

      msgAtual += `📑 <b>DOCUMENTOS E ANEXOS PUBLICADOS:</b>\n`;
      for (const l of linksDocumentos) {
        let filename = decodeURIComponent(l.split('/').pop());
        msgAtual += `  • <a href="${l}">${filename}</a>\n`;
      }
      msgAtual += `\n`;

      msgAtual += `🎓 <b>LISTA DE CONVOCADOS (TOTAL: ${totalConvocados}):</b>\n`;

      for (const item of relatorioCursos) {
        let blocoCurso = `📌 <b>${item.curso.toUpperCase()}</b> (${item.convocados.length} convocados):\n`;
        for (const c of item.convocados) {
          blocoCurso += `  • <b>${c.posicao}º</b> - ${c.nome} [${c.situacao}]\n`;
        }
        blocoCurso += `\n`;

        if ((msgAtual + blocoCurso).length > 3500) {
          mensagensTelegram.push(msgAtual);
          msgAtual = `📌 <b>(CONTINUAÇÃO DE CONVOCADOS IFES)</b>\n\n` + blocoCurso;
        } else {
          msgAtual += blocoCurso;
        }
      }

      msgAtual += `✉️ <i>Dúvidas/Recursos: matricula.cai@ifes.edu.br</i>`;
      mensagensTelegram.push(msgAtual);

      await salvarEstado(env, estadoAtual);

    } else if (diff.temMudanca) {
      let msgDiff = `🚨 <b>ALERTA DE ATUALIZAÇÃO NO EDITAL IFES!</b>\n`;
      msgDiff += `<b>Página:</b> <a href="${targetUrl}">Chamada Pública IFES</a>\n\n`;

      if (diff.modificacaoDataMudou) {
        msgDiff += `🕒 <b>DATA DE ATUALIZAÇÃO NO SITE MUDOU:</b>\n`;
        msgDiff += `  • De: <code>${diff.modificacaoAnterior}</code>\n`;
        msgDiff += `  • Para: <code>${diff.modificacaoNova}</code>\n\n`;
      }

      if (diff.cronogramaMudou.length > 0) {
        msgDiff += `📅 <b>ALTERAÇÕES NO QUADRO DE DATAS (CRONOGRAMA):</b>\n`;
        for (const alteracao of diff.cronogramaMudou) {
          msgDiff += `  ${alteracao}\n`;
        }
        msgDiff += `\n`;
      }

      if (diff.novosLinks.length > 0) {
        msgDiff += `📑 <b>NOVOS DOCUMENTOS/ANEXOS PUBLICADOS:</b>\n`;
        for (const l of diff.novosLinks) {
          let filename = decodeURIComponent(l.split('/').pop());
          msgDiff += `  • <a href="${l}">${filename}</a>\n`;
        }
        msgDiff += `\n`;
      }

      if (diff.convocadosMudaram) {
        msgDiff += `🎓 <b>ALTERAÇÃO NA LISTA DE CONVOCADOS:</b>\n`;
        msgDiff += `  • Total de convocados mudou de ${estadoAnterior.totalConvocados} para ${totalConvocados}.\n\n`;
      }

      msgDiff += `🔔 <i>Verifique o site oficial para mais informações.</i>`;
      mensagensTelegram.push(msgDiff);

      await salvarEstado(env, estadoAtual);
    }

    const token = env.TELEGRAM_TOKEN || "8928855109:AAGU-Pa-6btwGYN2qVZhqbQ7M3pO9-aGKnU";
    const chatId = overrideChatId || env.TELEGRAM_CHAT_ID || "5549055698";

    if (token && chatId && mensagensTelegram.length > 0) {
      for (const msgPart of mensagensTelegram) {
        await enviarTelegram(token, chatId, msgPart, workerUrl);
      }
    }

    return {
      status: "sucesso",
      temMudanca: diff.temMudanca,
      primeiraExecucao: diff.primeiraExecucao,
      ultimaModificacaoSite: meta.modificado,
      quadroDeDatas: cronograma,
      documentosAnexos: linksDocumentos,
      totalConvocados: totalConvocados,
      totalCursos: relatorioCursos.length,
      mensagensEnviadas: mensagensTelegram.length
    };

  } catch (error) {
    console.error("Erro na verificação do edital:", error);
    return { status: "erro", mensagem: error.message };
  }
}

async function enviarTelegram(token, chatId, text, workerUrl = "") {
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const body = {
    chat_id: chatId,
    text: text,
    parse_mode: "HTML",
    disable_web_page_preview: true
  };

  if (workerUrl) {
    body.reply_markup = {
      inline_keyboard: [
        [{ text: "🔄 Consultar IFES Agora em Tempo Real", url: workerUrl }]
      ]
    };
  }

  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}
