Leia em: [English](README.md) | Português

# Sala de escuta

Uma sala de escuta para o Spotify: um painel web que roda no seu PC, acha músicas que você nunca
ouviu e toca direto no seu Spotify. Você e até quatro amigos entram cada um com a própria conta,
em português ou inglês.

- **Sensações**: escreva o que está sentindo (ou escolha um momento) e receba músicas no ritmo certo.
- **Descobrir**: uma roleta de discos pouco ouvidos do mundo todo e uma toca do coelho que pula de
  um artista que você curte para os menos conhecidos.
- **Novidades**: o que acabou de sair num gênero, só de artistas do tamanho que você escolher.
- **Artistas**: tudo o que uma banda ou artista lançou, com o trabalho solo de cada integrante e as participações.
- **Favoritas que se atualizam sozinhas**: transforme uma seleção numa playlist que ganha músicas
  novas todo dia, toda semana ou todo mês. Só essas playlists especiais ficam na barra do topo.
- **Início**: uma sugestão para a hora do dia, o que está tocando, suas favoritas, atalhos e achados recentes.
- **Estante curada** (dono): 5 playlists do `playlists.json`, incluindo uma semanal de podcasts.

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

A sua estante curada fica em `playlists.json`, criado a partir do `playlists.example.json` na primeira vez.
Ele é seu: fica fora do git, e o painel escreve nele quando você adiciona faixas.

## O painel

O painel abre em http://127.0.0.1:8888 e fica no ar enquanto a janela preta estiver aberta.
Na primeira visita aparece uma apresentação curta com o mascote; **Como funciona**, no topo, abre de novo.
**PT / EN** troca o idioma daquela pessoa (as mensagens do servidor acompanham).

- **Barra**: no topo, "Favoritas" (playlists que se atualizam sozinhas, mais as que você fixar) e "Sala" (Início,
  Sensações, Descobrir, Novidades). Cada favorita é uma lombada colorida, e a escolhida vira a luz do
  painel. O mascote ao lado do nome também volta para o Início.
- **Início**: "Pra agora" sugere uma sensação para a hora do dia (manhã, tarde, noite; festa nas noites
  de sexta e sábado) e toca na hora se ela já for favorita; "Tocando agora"; suas favoritas com a
  próxima atualização; atalhos para a roleta, a toca e as novidades do último gênero que você buscou;
  e as músicas que você guardou por último.
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

Escolha um gênero (ex.: K-pop), o tamanho do artista e o período (hoje, ou os últimos 3, 7, 14, 30 ou 90 dias). A sala
levanta artistas do gênero em playlists, filtra pelos fãs, olha os lançamentos de cada um e mostra a
faixa principal de cada lançamento, do mais novo para o mais antigo. Versões "clean" do mesmo
lançamento são juntadas, e em trilhas sonoras vale a faixa do próprio artista.

### Artistas

Digite uma banda ou um artista, de qualquer gênero (ex.: Racionais MC's, TWICE, Coldplay), e veja tudo
o que lançou: álbuns, singles e EPs, participações em músicas de outros artistas, coletâneas e trilhas,
mais o trabalho solo e as participações de cada integrante e subunidade (inclusive ex-integrantes).
Filtre por pessoa e por tipo, e ordene dos mais recentes ou dos mais antigos. Uma participação toca a
partir da faixa em que a pessoa aparece.

Quem faz parte de uma banda vem do [MusicBrainz](https://musicbrainz.org) (dados abertos, sem chave; um
pedido por segundo, guardado por um mês em `data/musicbrainz-cache.json`), que também liga cada pessoa
ao perfil dela no Spotify. Integrantes sem esse link são procurados pelo nome, e ficam de fora quando o
nome é ambíguo. Essa busca quase não usa a busca da Spotify, então funciona mesmo com a busca pausada.

### Guardar o que gostou

Acima de cada resultado:

- **Criar playlist**: tudo o que apareceu vira uma playlist com o nome que você escolher (já vem
  preenchido, ex.: "Sensação: Foco profundo"). Se você já tem uma com esse nome, a sala pergunta
  antes de trocar as músicas dela. **Atualizar sozinha** (todo dia, toda semana ou todo mês) a
  transforma em favorita: ela vai para a barra e, a cada atualização, a mesma descoberta roda de novo
  e as músicas são trocadas por uma seleção nova.
- **Adicionar a uma playlist**: manda tudo para `Achados da Sala` (criada na primeira vez) ou para
  qualquer playlist sua. Músicas que já estão lá não se repetem.

Cada música tem o próprio **Adicionar**, com as mesmas opções. Playlists que a sala remonta sozinha
(a semanal de podcasts e a mistura) não aparecem ali, porque o que entrasse nelas se perderia.

Na página de uma favorita: **Atualizar agora**, a frequência e **Tirar da barra** (a playlist
continua no Spotify; só para de se atualizar). O **+** no fim das favoritas (ou **Pôr playlist na barra**,
no Início) fixa qualquer playlist sua como atalho, sem atualização automática, e traz de volta as da
curadoria que saíram da barra. Até 8 favoritas por pessoa. As atualizações rodam
dentro do painel, uma de cada vez e no máximo uma a cada 10 minutos, para poupar os limites da
Spotify; enquanto a Spotify estiver com a busca pausada, elas esperam. Se o PC estava desligado na
hora, a atualização roda assim que o painel voltar.

O ⓘ de cada música mostra por que ela apareceu (BPM e energia medidos, o gênero ou ano sorteado,
os pulos da toca, a data do lançamento) e tem **Não mostrar mais**: o artista some na hora e nunca
mais volta em nenhuma descoberta. A lista é de cada pessoa; para desfazer, use **Artistas bloqueados**
acima dos resultados.

**Nada religioso**: as descobertas descartam faixas, álbuns e playlists com sinais religiosos de
qualquer denominação (`RELIGIOUS_WORDS` em `spotify_assistant/discovery.py`).

### Estante curada (dono)

| Playlist | Conteúdo | Atualiza (padrão) |
|---|---|---|
| Tech Radar BR | episódios recentes de podcasts de tecnologia em PT-BR | toda semana |
| Midnight in Monaco | jazz sofisticado | todo mês |
| Deep Focus — Lo-Fi | lo-fi para programar (embaralhado) | todo mês |
| The Classical Room | clássico, do contemplativo ao grandioso | todo mês |
| The Study Collection | jazz + lo-fi + clássico, alternados | todo mês |

As playlists curadas são as favoritas do dono; a frequência muda na página de cada uma, e **Tirar da
barra** esconde uma delas (ela para de se atualizar até voltar pelo **+**).

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

Cada pessoa entra com o próprio Spotify e tem player, descobertas, favoritas, Achados e bloqueados
só dela. Ninguém vê as playlists nem as buscas dos outros. O painel
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

Com isso ligado, `open-panel.cmd` só abre a sala no navegador, e as favoritas se atualizam sozinhas.

## Linha de comando

```powershell
python -m spotify_assistant login            # entra com a conta do dono (só uma vez)
python -m spotify_assistant check            # mostra o dono e quem está na sala
python -m spotify_assistant setup --dry-run  # mostra o que seria criado, sem alterar nada
python -m spotify_assistant setup            # cria/recria as 5 playlists
python -m spotify_assistant setup --only "Midnight in Monaco"
python -m spotify_assistant refresh          # atualiza agora as favoritas no prazo, de todos
```

O `refresh` só é necessário se você não deixa o painel aberto (o painel faz isso sozinho).
`SALA_LANG` no `.env` (`en` ou `pt`) define o idioma da linha de comando e das atualizações automáticas.

## Personalizar

Tudo fica em `playlists.json` (a sua cópia do `playlists.example.json`):

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
- `users/<id>/favorites.json`, `recent.json`: favoritas (receita, frequência, última atualização) e achados recentes.
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

## Licença

[MIT](LICENSE). Sem vínculo com a Spotify; usa a Web API do Spotify sob os termos de desenvolvedor da Spotify.
