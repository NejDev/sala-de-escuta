Leia em: [English](README.md) | Português

# Sala de escuta

Uma sala de escuta para o Spotify: um painel web que roda no seu PC, acha músicas que você nunca
ouviu e toca direto no seu Spotify. Você e até quatro amigos entram cada um com a própria conta,
em português ou inglês.

- **Sensações**: escreva o que está sentindo (ou escolha um momento) e receba músicas no ritmo certo.
- **Descobrir**: uma roleta de discos pouco ouvidos do mundo todo e uma toca do coelho que pula de
  um artista que você curte para os menos conhecidos.
- **Novidades**: o que acabou de sair num gênero, só de artistas do tamanho que você escolher.
- **Guarde o que gostou**: transforme qualquer seleção em playlist, ou adicione uma música a uma sua.
- **Estante curada** (dono): 5 playlists mantidas em dia, incluindo uma semanal de podcasts.

Python 3.12. Tudo usa só a biblioteca padrão, menos a medição de BPM das Sensações, que precisa de
um decodificador de MP3 (`pip install -r requirements.txt`).

## Rodar a sua própria sala

A Spotify só deixa apps pequenos funcionarem em **Development Mode**: até 5 pessoas (contando o dono),
cada uma liberada à mão, e a conta dona do app precisa ser Premium. Mais usuários exigem a "cota
estendida", que a Spotify só concede a organizações registradas com pelo menos 250 mil usuários por
mês ([modos de cota](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)).
Por isso, o jeito de compartilhar este projeto é cada pessoa rodar a própria sala:

1. Crie um app no [Spotify for Developers](https://developer.spotify.com/dashboard) (Web API).
   Adicione `http://127.0.0.1:8888/callback` nas Redirect URIs.
2. Copie `.env.example` para `.env` e preencha `SPOTIFY_CLIENT_ID`. Sem Client Secret: o login usa PKCE.
3. `pip install -r requirements.txt` e dê dois cliques em `open-panel.cmd`
   (ou rode `python -m spotify_assistant ui`).
4. Entre. A primeira pessoa que entrar vira a dona da sala.

## O painel

O painel abre em http://127.0.0.1:8888 e fica no ar enquanto a janela preta estiver aberta.
Na primeira visita aparece uma apresentação curta com o mascote; **Como funciona**, no topo, abre de novo.
**PT / EN** troca o idioma daquela pessoa (as mensagens do servidor acompanham).

- **Estante**: no topo, em duas seções, "Playlists" e "Explorar". Cada playlist é uma lombada
  colorida, e a escolhida vira a luz do painel.
- **Player**: tocar, pausar, pular, aleatório, repetir (desligado, tudo, esta faixa), volume e
  progresso. Clique numa faixa para tocar a partir dela. Funciona com o Spotify aberto no PC ou no
  celular (exige Premium). Na primeira vez, clique em **Autorizar no Spotify** na barra de baixo.
- **Atalhos**: espaço toca/pausa, ← → trocam de faixa, 1–9 trocam de tela.

### Sensações

**Escreva o que está sentindo** ("ódio", "saudade de casa", "anger", "missing home") ou escolha um
momento pronto. O texto livre não usa nenhuma IA paga:

1. A frase vira a primeira busca: muita gente batiza playlists com sentimentos.
2. Um dicionário local (`FEELINGS`, em `spotify_assistant/discovery.py`, em português e inglês)
   reconhece o sentimento, define o ritmo (ódio: 125–185 BPM e energia alta) e amplia as buscas.
3. Se a frase não está no dicionário ("domingo de manhã"), a sala ouve as prévias, descobre o BPM e
   a energia que elas têm em comum e fica com as músicas que seguem esse padrão.

Nos momentos prontos (treino pesado, corrida, foco profundo, festa, dia de chuva...) a sala procura
playlists que pessoas montaram para aquele momento, **ouve a prévia de 30 s de cada faixa e mede BPM
e energia**, e fica só com o que cabe na faixa daquela sensação. **Fãs do artista** (no mínimo /
no máximo) restringe a artistas do tamanho que você quiser.

Por que medir? A Spotify parou de entregar BPM para apps novos, e o BPM dos catálogos públicos quase
sempre vem zerado. O medidor (`spotify_assistant/tempo.py`) acertou 12 de 17 músicas de BPM conhecido,
mais 2 no dobro/metade; trate o número como aproximado.

Os momentos ficam em `sensations.json` (nome e descrição nos dois idiomas, faixa de BPM, faixa de
energia de 0 a 1, cor e as buscas usadas como fonte). As medições ficam em `data/tempo-cache.json`
para não ouvir a mesma prévia duas vezes.

### Descobrir

- **Roleta**: o mascote revira um caixote de discos enquanto sorteia álbuns pouco ouvidos de um ano
  qualquer e faixas menos populares de playlists de gêneros do mundo todo (zamrock, enka, huayno,
  ethio jazz...). A lista de gêneros é `WORLD_GENRES`, em `spotify_assistant/discovery.py`.
- **Toca do coelho**: parte de um artista (digitado ou sorteado das suas playlists) e pula 4 vezes
  para artistas relacionados, sempre entre os menos conhecidos. Mostra o caminho todo e o número de fãs.

As duas aceitam um gênero opcional (roleta) e o tamanho do artista em fãs (mínimo e máximo). Nenhuma
API gratuita diz quantas vezes uma música foi tocada; o número de fãs do artista é a medida disponível.

### Novidades

Escolha um gênero (ex.: K-pop), o tamanho do artista e o período (7, 14, 30 ou 90 dias). A sala
levanta artistas do gênero em playlists, filtra pelos fãs, olha os lançamentos de cada um e mostra a
faixa principal de cada lançamento, do mais novo para o mais antigo. Versões "clean" do mesmo
lançamento são juntadas, e em trilhas sonoras vale a faixa do próprio artista.

### Guardar o que gostou

Acima de cada resultado:

- **Criar playlist**: tudo o que apareceu vira uma playlist com o nome que você escolher (já vem
  preenchido, ex.: "Sensação: Foco profundo"). Se você já tem uma com esse nome, a sala pergunta
  antes de trocar as músicas dela.
- **Adicionar a uma playlist**: manda tudo para `Achados da Sala` (criada na primeira vez) ou para
  qualquer playlist sua. Músicas que já estão lá não se repetem.

Cada música tem o próprio **Adicionar**, com as mesmas opções. Playlists que a sala remonta sozinha
(a semanal de podcasts e a mistura) não aparecem ali, porque o que entrasse nelas se perderia.

O ⓘ de cada música mostra por que ela apareceu (BPM e energia medidos, o gênero ou ano sorteado,
os pulos da toca, a data do lançamento) e tem **Não mostrar mais**: o artista some na hora e nunca
mais volta em nenhuma descoberta. A lista é de cada pessoa; para desfazer, use **Artistas bloqueados**
acima dos resultados.

**Nada religioso**: as descobertas descartam faixas, álbuns e playlists com sinais religiosos de
qualquer denominação (`RELIGIOUS_WORDS` em `spotify_assistant/discovery.py`).

### Estante curada (dono)

| Playlist | Conteúdo | Atualiza |
|---|---|---|
| Tech Radar BR | episódios recentes de podcasts de tecnologia em PT-BR | toda semana (automático) |
| Midnight in Monaco | jazz sofisticado | `setup` |
| Deep Focus — Lo-Fi | lo-fi para programar (embaralhado) | `setup` |
| The Classical Room | clássico, do contemplativo ao grandioso | `setup` |
| The Study Collection | jazz + lo-fi + clássico, alternados | `setup` |

- **Atualizar agora / Refazer seleção** roda a curadoria com o log aparecendo ao vivo; **Ver prévia**
  mostra o resultado sem alterar nada.
- **Adicionar faixa / Acompanhar outro programa** busca no catálogo. A faixa entra na playlist na
  hora e no `playlists.json`, para sobreviver ao próximo `setup`. Músicas adicionadas de uma
  descoberta a uma playlist curada também vão para o `playlists.json`.
- As cores das lombadas são o campo `color` de cada playlist no `playlists.json`.

### Custo

Zero. A Web API do Spotify e a API pública do Deezer são gratuitas (só têm limite de pedidos, que o
painel respeita), o BPM é medido no seu PC e o texto livre é lido localmente.

## Sala para amigos

Cada pessoa entra com o próprio Spotify e tem player, descobertas, Achados, bloqueados e cópias das
playlists só dela ("Criar no meu Spotify"). Ninguém vê as playlists nem as buscas dos outros. O painel
roda no PC do dono e fica público pelo [Tailscale Funnel](https://tailscale.com/kb/1223/funnel), num
endereço fixo `https://<pc>.<rede>.ts.net`.

1. Ponha em `SALA_PUBLIC_URL`, no `.env`, o endereço do Funnel (`tailscale funnel status` mostra).
2. No app do Spotify for Developers → Settings, adicione `<SALA_PUBLIC_URL>/callback` em Redirect URIs.
3. Em User Management, adicione o nome e o e-mail da conta Spotify de cada amigo (5 pessoas no total,
   contando o dono).
4. Mande o endereço. O player só funciona para quem tem Premium; descobrir e guardar funcionam para todos.

O site só fica no ar com o PC ligado e o painel aberto. Para o painel abrir sozinho, escondido,
toda vez que você entra no Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1           # liga
powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1 -Remove   # desfaz
```

Com isso ligado, `open-panel.cmd` só abre a sala no navegador. O `weekly` atualiza a Tech Radar de
todos que a criaram.

## Linha de comando

```powershell
python -m spotify_assistant login            # entra com a conta do dono (só uma vez)
python -m spotify_assistant check            # mostra o dono e quem está na sala
python -m spotify_assistant setup --dry-run  # mostra o que seria criado, sem alterar nada
python -m spotify_assistant setup            # cria/recria as 5 playlists
python -m spotify_assistant setup --only "Midnight in Monaco"
python -m spotify_assistant weekly           # atualiza só a Tech Radar BR
```

`SALA_LANG` no `.env` (`en` ou `pt`) define o idioma da linha de comando e da tarefa semanal.

Agende a atualização semanal (segunda às 09:00; se o PC estiver desligado, roda assim que ligar):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\schedule-weekly.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\schedule-weekly.ps1 -Day Friday -Time 18:30
```

## Personalizar

Tudo fica em `playlists.json`:

- `tracks`: `"Artista - Título"`. A busca descarta versões karaokê, lo-fi, de ninar etc.
- `artists`: pega as `per_artist` faixas mais relevantes de cada artista.
- `podcasts.shows`: nomes dos programas; `max_age_days` define o que conta como "recente".
- `mix`: sorteia `per_source` faixas de cada playlist listada e alterna entre elas.

O que não for encontrado aparece como `não encontrado:` na saída. É só ajustar o nome no JSON.

Os textos da interface ficam em `spotify_assistant/static/i18n.js` (navegador) e
`spotify_assistant/i18n.py` (servidor); `tests/test_i18n.py` confere que os dois idiomas têm as mesmas chaves.

## Arquivos locais (em `data/`, nunca vão para o git)

- `users/<id>/token.json`: o token de acesso de cada pessoa. Não compartilhe.
- `users/<id>/state.json`, `blocked.json`, `profile.json`: IDs das playlists, artistas bloqueados e nome.
- `owner.txt`, `sessions.json`: quem é o dono da sala e as sessões dos navegadores.
- `tempo-cache.json`, `spotify-matches.json`, `spotify-pauses.json`: BPMs medidos, faixas já
  localizadas no Spotify e as pausas de pedidos da Spotify.
- `assistant.log`: histórico das execuções (inclusive as agendadas).

## Problemas comuns

- **403 / "Sua conta ainda não foi liberada"**: em Development Mode a conta dona do app precisa ser
  Premium e o e-mail de cada pessoa precisa estar em *User Management*.
- **"Sua sessão do Spotify expirou"**: entre de novo (ou `python -m spotify_assistant login` para o dono).
- **"A Spotify pausou as buscas deste app"**: o app fez pedidos demais e a Spotify suspendeu a busca
  por algumas horas (player e playlists continuam funcionando). O painel respeita a pausa, mostra
  quando volta e guarda as músicas já encontradas para não buscá-las de novo. Evite deixar várias
  abas do painel abertas: cada uma consulta o player.
