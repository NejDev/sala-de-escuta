# Spotify Assistant

Cria e mantém 5 playlists na sua conta:

| Playlist | Conteúdo | Atualização |
|---|---|---|
| Tech Radar BR | episódios recentes de podcasts tech PT-BR | semanal (automática) |
| Midnight in Monaco | jazz refinado | `setup` |
| Deep Focus — Lo-Fi | lo-fi para programar (embaralhada) | `setup` |
| The Classical Room | clássica, do contemplativo ao grandioso | `setup` |
| The Study Collection | jazz + lo-fi + clássica alternados | `setup` |

Python 3.12. As playlists e o painel usam só a biblioteca padrão; medir BPM nas **Sensações**
precisa de um decodificador de MP3:

```powershell
pip install -r requirements.txt
```

## Painel visual

Dê dois cliques em `abrir-painel.cmd` (ou rode `python -m spotify_assistant ui`). O painel abre em
http://127.0.0.1:8888 e fica no ar enquanto a janela preta estiver aberta.

- **Estante**: no topo, em duas seções ("Suas playlists" e "Explorar"); cada playlist é uma lombada
  colorida e a escolhida vira a cor do painel.
- **Player**: tocar, pausar, pular, aleatório, volume e barra de progresso. Clique numa faixa para
  tocar a partir dela. Funciona com o Spotify aberto no PC ou no celular (exige Premium).
- **Atualizar agora / Refazer seleção**: roda a curadoria com o log aparecendo ao vivo.
  **Ver prévia** mostra o resultado sem mexer em nada.
- **Adicionar faixa / Acompanhar outro programa**: busca no catálogo. A faixa entra na playlist
  na hora e também no `playlists.json`, para não sumir no próximo `setup`.
- **Atalhos**: espaço toca/pausa, ← → trocam de faixa, 1–7 trocam de lombada.

Na primeira vez, clique em **Autorizar no Spotify** na barra de baixo para liberar o controle do player.

As cores das lombadas ficam no campo `color` de cada playlist no `playlists.json`.

### Sensações

**Escreva o que está sentindo** ("ódio", "saudade de casa", "chorando no banho") ou escolha um momento
pronto. O texto livre não usa nenhuma IA paga:

1. A frase vira a primeira busca: muita gente batiza playlists com sentimentos.
2. Um dicionário local (`FEELINGS`, em `spotify_assistant/discovery.py`) reconhece o sentimento,
   define o ritmo (ódio: 125–185 BPM e energia alta) e amplia a busca ("rage music", "metal pesado").
3. Se a frase não estiver no dicionário ("domingo de manhã"), a sala ouve as prévias, descobre o
   BPM e a energia que elas têm em comum e fica com as músicas que seguem esse padrão.

Nos momentos prontos (treino pesado, corrida, foco profundo, festa, dia de chuva...) a sala busca
playlists que pessoas montaram para esse momento no Deezer, **ouve a prévia de 30 s de cada faixa e
mede BPM e energia**, e fica só com o que cabe na faixa daquela sensação. As músicas aparecem
conforme são aprovadas; dá para tocar tudo direto no Spotify ou salvar como playlist
`Sensação: <nome>` (sempre a mesma, atualizada a cada vez que você salvar).

Por que medir? A Spotify parou de entregar BPM para apps novos e o BPM do Deezer quase sempre vem
zerado. O medidor (`spotify_assistant/tempo.py`) acertou 12 de 17 músicas com BPM conhecido e
outras 2 no dobro/metade do tempo; trate o número como aproximado.

As sensações ficam em `sensacoes.json`: faixa de BPM, faixa de energia (0 a 1), cor e as buscas
usadas como fonte. Medições ficam em `data/tempo-cache.json` para não ouvir a mesma prévia duas vezes.

### Descobrir

- **Roleta**: um bonequinho garimpa um caixote de discos enquanto sorteia álbuns pouco ouvidos de um ano qualquer e faixas menos populares de playlists
  de gêneros do mundo todo (zamrock, enka, huayno, ethio jazz...). A lista de gêneros fica em
  `WORLD_GENRES`, no `spotify_assistant/discovery.py`.
- **Toca do coelho**: parte de um artista (digitado ou sorteado das suas playlists) e pula 4 vezes
  para artistas relacionados, sempre entre os menos conhecidos. Mostra o caminho e o número de fãs.

**Nada religioso**: a descoberta descarta faixas, álbuns e playlists com sinais religiosos de qualquer
denominação (lista `RELIGIOUS_WORDS` em `spotify_assistant/discovery.py`). Uma playlist inteira é
descartada quando várias faixas dela têm esses sinais.

**Não mostrar mais**: no ⓘ de cada música há um botão para bloquear o artista. Ele some na hora e
nunca mais aparece em Sensações ou Descobrir. A lista fica em `bloqueados.json`; para desfazer, use
"Artistas bloqueados" acima dos resultados.

**Guardar** manda a faixa para a playlist `Achados da Sala`, criada na primeira vez. O ⓘ de cada
música mostra por que ela apareceu (BPM e energia medidos, gênero ou ano sorteado, de onde a toca partiu).

### Custo

Zero. A Spotify Web API e a API pública do Deezer são gratuitas (só têm limite de requisições, que o
painel respeita), o BPM é medido no seu PC e o texto livre é interpretado localmente.

## Sala para amigos

Cada pessoa entra com o próprio Spotify e tem player, buscas, Achados, bloqueados e a própria cópia
das playlists (botão "Criar no meu Spotify"). O painel roda no PC do dono e fica público pelo
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel), num endereço fixo `https://<pc>.<rede>.ts.net`.

1. `SALA_PUBLIC_URL` no `.env` com o endereço do Funnel (`tailscale funnel status` mostra).
2. No app do Spotify for Developers → Settings: adicione `<SALA_PUBLIC_URL>/callback` em Redirect URIs.
3. Em User Management, adicione nome e e-mail da conta Spotify de cada amigo (limite de 5 pessoas,
   contando o dono, no Development Mode).
4. Mande o endereço para eles. O player só funciona para quem tem Premium; descobrir e salvar, para todos.

O site só fica no ar com o PC ligado e o painel aberto. A seleção base das playlists (`playlists.json`)
é do dono; amigos adicionam faixas só nas próprias cópias. `weekly` atualiza a Tech Radar de todos que a criaram.

## Linha de comando

```powershell
python -m spotify_assistant login            # abre o navegador para autorizar (uma vez só)
python -m spotify_assistant check            # mostra a conta conectada
python -m spotify_assistant setup --dry-run  # mostra o que seria criado, sem mexer em nada
python -m spotify_assistant setup            # cria/recria as 5 playlists
python -m spotify_assistant setup --only "Midnight in Monaco"
python -m spotify_assistant weekly           # atualiza só a Tech Radar BR
```

Agendar a atualização semanal (segunda às 09:00; se o PC estiver desligado, roda quando ligar):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agendar-semanal.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\agendar-semanal.ps1 -Dia Friday -Hora 18:30
```

## Personalizar

Tudo está em `playlists.json`:

- `tracks`: `"Artista - Título"`. A busca ignora versões karaokê, lo-fi, de ninar, etc.
- `artists`: pega as `per_artist` faixas mais relevantes de cada artista.
- `podcasts.shows`: nome dos programas; `max_age_days` define o que conta como "recente".
- `mix`: sorteia `per_source` faixas de cada playlist listada e alterna entre elas.

O que não for encontrado aparece como `não encontrado:` na saída. Basta ajustar o nome no JSON.

## Arquivos locais

- `.env`: só o Client ID. O login usa PKCE, então **o Client Secret não é usado**.
- `data/token.json`: seu token de acesso. Não compartilhe.
- `data/state.json`: IDs das playlists/podcasts, para não duplicar.
- `data/assistant.log`: histórico das execuções (inclusive as agendadas).

## Problemas comuns

- **403**: no Development Mode (regras de fev/2026), a conta dona do app precisa ser Premium e
  seu e-mail precisa estar em *User Management* no app do Spotify for Developers.
- **"sessão expirou"**: rode `python -m spotify_assistant login` de novo.
- **"A Spotify pausou as buscas"**: o app fez pedidos demais e a Spotify suspendeu a busca por algumas
  horas (player e playlists continuam funcionando). O painel respeita a pausa sozinho, mostra a hora
  em que volta e guarda as músicas já localizadas para não buscar de novo. Evite deixar várias abas
  do painel abertas: cada uma consulta o player.
