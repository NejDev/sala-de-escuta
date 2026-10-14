# Spotify Assistant

Cria e mantém 5 playlists na sua conta:

| Playlist | Conteúdo | Atualização |
|---|---|---|
| Tech Radar BR | episódios recentes de podcasts tech PT-BR | semanal (automática) |
| Midnight in Monaco | jazz refinado | `setup` |
| Deep Focus — Lo-Fi | lo-fi para programar (embaralhada) | `setup` |
| The Classical Room | clássica, do contemplativo ao grandioso | `setup` |
| The Study Collection | jazz + lo-fi + clássica alternados | `setup` |

Só usa a biblioteca padrão do Python 3.12, sem `pip install`.

## Painel visual

Dê dois cliques em `abrir-painel.cmd` (ou rode `python -m spotify_assistant ui`). O painel abre em
http://127.0.0.1:8888 e fica no ar enquanto a janela preta estiver aberta.

- **Estante**: cada playlist é uma lombada colorida; a escolhida vira a cor do painel.
- **Player**: tocar, pausar, pular, aleatório, volume e barra de progresso. Clique numa faixa para
  tocar a partir dela. Funciona com o Spotify aberto no PC ou no celular (exige Premium).
- **Atualizar agora / Refazer seleção**: roda a curadoria com o log aparecendo ao vivo.
  **Ver prévia** mostra o resultado sem mexer em nada.
- **Adicionar faixa / Acompanhar outro programa**: busca no catálogo. A faixa entra na playlist
  na hora e também no `playlists.json`, para não sumir no próximo `setup`.
- **Atalhos**: espaço toca/pausa, ← → trocam de faixa, 1–5 trocam de playlist.

Na primeira vez, clique em **Autorizar no Spotify** na barra de baixo para liberar o controle do player.

As cores das lombadas ficam no campo `color` de cada playlist no `playlists.json`.

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
