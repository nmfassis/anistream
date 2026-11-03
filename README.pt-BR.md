# anistream

[English](README.md) · **Português**

Assista aos animes das suas listas do AniList pelo terminal, com o próximo episódio a um toque. O vídeo toca no **mpv**, numa janela
própria ou **dentro do terminal** (sixel, do jeito que o port do yt-terminal faz). Sincronizar os episódios assistidos com o AniList é
**opcional**.

> **Versão: 0.1.8.** Os logs de diagnóstico ficam ocultos durante o uso normal; no modo janela a saída do mpv é redirecionada, e o modo sixel mantém o stdout para o vídeo. Consulte o [índice da documentação](docs/README.md) para os guias de comandos, configuração, arquitetura e solução de problemas.

## O que faz

- **Suas listas prontas para assistir.** *Continue watching* mostra o que você está vendo com `▶ Ep 3 ready`, ou `Ep 5 airs in 2d 4h` quando
  você está em dia. Também há *Planning* e *busca* no AniList.
- **Escolha automática do catálogo.** A correspondência usa primeiro o ID do AniList embutido no catálogo; sem ele, compara título e temporada/stage com rigor. O seletor manual só aparece quando não há uma correspondência confiável.
- **Fallback de fontes.** Tenta os dois catálogos configurados do `ani-cli-rs`, outros links se um fechar logo, e depois a outra versão de áudio quando habilitada. No modo legendado, prioriza links que exponham faixas de legenda.
- **Toca pelo mpv sem poluir o terminal.** Os logs de diagnóstico ficam ocultos por padrão; no modo janela a saída do mpv é redirecionada e o modo sixel mantém o stdout para o vídeo, ocultando o stderr. Modo janela ou `--player sixel` para vídeo dentro de um terminal com suporte a sixel (como o Windows Terminal). Os cabeçalhos da requisição (Referer…) e as legendas do stream são repassados ao mpv.
- **O anime certo, o stage certo.** A entrada do catálogo é escolhida pelo id do AniList que o catálogo traz, quando existe, senão por uma
  verificação rigorosa das palavras **e** dos números de temporada/stage ("1st STAGE" ≠ "2nd - 3rd STAGE"). As mesmas regras do
  [anilist-autodl](https://github.com/nmfassis/anilist-autodl).
- **Sincronização opcional, nunca destrutiva.** Quando um episódio conta como assistido (padrão 85%), o progresso sobe no AniList;
  Planning/Paused → Watching no primeiro episódio; → Completed no último, com datas de início/fim só se faltarem. O progresso nunca diminui;
  notas, pontuação e outros campos nunca são tocados. Sem internet, a atualização entra numa fila e é enviada na próxima vez.
- **Legendado ou dublado**, com alternativa automática quando a versão preferida não tem stream.

## Instalar

**Uma linha** (Git Bash no Windows, ou Linux/macOS). Precisa de Python 3.8+ e cria o comando `anistream`, sem pip:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USER/anistream/main/install.sh | bash
```

Num clone, `bash install.sh` faz o mesmo com os arquivos locais; `bash install.sh --uninstall` remove. Rodar de novo atualiza.

Em ambos os casos você precisa de **Python 3.8+**, **mpv** e **ani-cli-rs**. O **fzf** é opcional (menus melhores).

**Windows**

```
winget install Python.Python.3.12
winget install mpv.mpv
winget install fzf                       # opcional
```

Instale o **ani-cli-rs** como descrito na [página de instalação](https://github.com/vorlie/ani-cli-rs/wiki/Installation) dele (há build
pronto para Windows x64; o `anistream` também procura em `%USERPROFILE%\.local\bin`, onde o instalador dele coloca).

Para instalar à mão, nesta pasta:

```
pip install .            # ou: pipx install .
anistream doctor         # confere tudo e diz o que falta
anistream
```

Sem instalar? Rode `anistream.cmd` (Windows) ou `./anistream.sh` (Linux/macOS) na pasta. Linux/macOS: mesmos passos com seu gerenciador
de pacotes (`apt install mpv fzf`, `brew install mpv fzf`).

## Usar

`anistream` abre os menus. Com fzf: digite para filtrar, Enter escolhe, Esc volta. Sem fzf: um número, um texto para filtrar, `b` volta,
`q` sai.

Depois de um episódio: **Próximo episódio · Repetir · Escolher episódio · Marcar como assistido · Voltar**.

```
anistream                              # menus
anistream play "dandadan"              # seu próximo episódio desse anime
anistream play "dandadan" -e 3         # um episódio específico
anistream --mode dub play "frieren"    # dublado nesta execução
anistream --player sixel               # vídeo dentro do terminal
anistream --no-sync                    # não envia nada ao AniList nesta execução
anistream --debug                      # mostra os comandos do ani-cli-rs que são executados
anistream probe "dandadan" -e 3       # por catálogo: o que bateu, há stream? (não toca nada)
anistream doctor
anistream auth
anistream config
```

## Sincronização com o AniList (opcional)

Ler suas listas só precisa do seu usuário. Para **atualizar** a lista você conecta a conta uma vez:

1. `anistream auth` (ou *Settings → Sync*).
2. Abra <https://anilist.co/settings/developer> → *Create New Client*. Nome: qualquer um. **Redirect URL:
   `https://anilist.co/api/v2/oauth/pin`**. Copie o client ID.
3. Informe o client ID; o navegador abre a página de autorização do AniList; cole o token que ela mostra.

O token fica no arquivo de configuração (`%APPDATA%\anistream\config.json` no Windows, `~/.config/anistream/config.json` nos demais;
permissão privada no Linux/macOS; no Windows ele fica no seu perfil, então trate como uma senha). Para não gravá-lo no arquivo, use a
variável `ANISTREAM_TOKEN`. Tokens duram cerca de um ano.

Quando um episódio conta? Com **85%** ou ao tocar até o fim, é registrado automaticamente. Entre **30% e 85%** você é perguntado. Abaixo de
30% nada acontece. Se o relatório de progresso não vier, você é perguntado. Pular adiante (ep. 7 estando no 3) pergunta antes.

### Chibi (backend opcional)

O [chibi-cli](https://github.com/CosmicPredator/chibi-cli) pode fazer o envio: `anistream config sync chibi`. Faça `chibi login` antes. O
anistream então roda só `chibi update <id> --progress <n>`.

Antes de escolher: o chibi guarda o token no chaveiro do sistema, então o anistream não consegue compartilhá-lo; e um problema conhecido
do projeto (#37) diz que o `chibi update` pode **apagar a data de início e as notas** da entrada. A sincronização embutida nunca faz isso,
por isso é a padrão. O backend chibi também não muda o status (Watching/Completed).

## Configurações

`anistream config` lista, `anistream config CHAVE VALOR` muda uma (também em *Settings*).

| Chave | Padrão | Significado |
| --- | --- | --- |
| `username` | – | seu usuário do AniList |
| `sync` | `anilist` | `anilist` (precisa de token), `chibi` ou `off` |
| `threshold` / `ask_below` | `85` / `30` | % que conta como assistido / % abaixo da qual nada é perguntado |
| `mode` / `mode_fallback` | `sub` / `true` | `sub` ou `dub`; tentar a outra quando faltar |
| `prefer_subtitles` | `true` | no modo legendado, tentar links com faixas de legenda antes dos que não expõem faixas |
| `quality` | `best` | `best`, `1080p`, `720p`… (preferida primeiro, nunca obrigatória) |
| `player_mode` | `window` | `window` ou `sixel` |
| `fullscreen` | `false` | só no modo janela |
| `mpv` / `mpv_args` | `mpv` / `[]` | executável e argumentos extras (`anistream config mpv_args '["--volume=60"]'`) |
| `title_lang` | `english` | `english` ou `romaji` |
| `use_fzf` | `true` | usar o fzf quando instalado |
| `providers` | `anikoto anikoto2` | catálogos do ani-cli-rs, em ordem |

## Solução de problemas

- **Primeiro passo para qualquer coisa:** `anistream doctor`; depois `anistream probe "nome" -e N` para um anime. Ele confere o mpv (e o suporte a sixel), o ani-cli-rs e os dois catálogos, o fzf, o AniList e seu token.
- **"No catalog entry matches this anime":** rode com `--debug` para ver as buscas. A correspondência exige as mesmas palavras e os mesmos
  números de temporada/stage; o "2nd & 3rd STAGE" do AniList é aceito quando o catálogo diz "2nd Stage".
- **`ACL-3001 No playable sources found`:** o provedor ainda não tem stream funcionando para esse episódio (geralmente um episódio novíssimo).
  Todos os catálogos são tentados em ordem e a mensagem diz o que cada um respondeu. Rode `anistream probe "nome" -e N` para ver isso em
  legendado e dublado; tente mais tarde ou com `--mode dub`.
- **mpv não encontrado:** `winget install mpv.mpv`. Para `--player sixel` no Windows usa-se o build de console `mpv.com`.
- **Assisti mas nada foi registrado:** veja o token em `anistream doctor`; abaixo de 85% você é perguntado; com `sync off` nada é enviado.
  Um envio que falhou entra na fila ("it will be retried next time").
- **O AniList diz que o token foi rejeitado:** rode `anistream auth` de novo.

## Limites e o que não foi verificado

- **Backends de streaming:** o anistream usa os dois catálogos independentes do `ani-cli-rs` (`anikoto`, `anikoto2`) e os links alternativos que eles expõem. O `ani-cli`, `ani-tupi` e GoAnime do projeto `anilist-autodl` são pipelines de download ou reprodução própria, não resolvedores que entreguem uma URL ao mpv e ao rastreador de progresso do anistream. Para integrá-los seria necessário um adaptador real de streaming ou um modo de player externo.
- **Confirmado num Windows de verdade:** o `doctor` passa com mpv, ani-cli-rs 0.11.2 e fzf, e a saída de busca dos dois catálogos é
  entendida. **Não verificado contra o real:** (1) os nomes exatos dos campos de `ani-cli-rs links --json` (o leitor aceita várias grafias;
  `anistream probe` e `--debug` mostram o que ele recebeu); (2) o `progress.lua`, o pequeno script do mpv que informa quanto você assistiu, foi escrito
  conforme a API documentada do mpv mas nunca rodou num mpv de verdade; (3) a saída sixel e o comportamento do Windows Terminal; (4) o fluxo
  PIN de autorização do AniList e as chamadas da API foram conferidos só contra um servidor falso. Reporte qualquer coisa estranha com a saída do `--debug`.
- Os streams são assinados e temporários: são resolvidos logo antes de tocar, nunca guardados.

## Documentação

Os guias completos estão em [`docs/`](docs/README.md): [comandos](docs/COMMANDS.md), [configuração e arquivos](docs/CONFIGURATION.md), [arquitetura](docs/ARCHITECTURE.md) e [solução de problemas](docs/TROUBLESHOOTING.md).

## Desenvolvimento

```
python -m unittest discover -s tests -v      # suíte offline existente
```

`anistream/matching.py` é o código de correspondência do anilist-autodl; mantenha os dois em sincronia se mudar as regras.

## Aviso sobre IA

Este projeto foi **100% feito com IA** (Claude, da Anthropic). Eu dirigi o trabalho por prompts, mas não escrevi nada à mão. Leia o código
antes de rodar e use por sua conta e risco.

## Isenção de responsabilidade

O anistream não hospeda nem fornece conteúdo; ele só toca streams que os catálogos pesquisados pelo ani-cli-rs expõem. Você é
responsável por seguir as leis de direitos autorais e os termos de serviço que se aplicam a você. Fornecido "como está", sem garantia de
qualquer tipo. Sem vínculo com AniList, ani-cli-rs, mpv ou Chibi.

## Créditos

[mpv](https://mpv.io), [ani-cli-rs](https://github.com/vorlie/ani-cli-rs), [API do AniList](https://anilist.gitbook.io/anilist-apiv2-docs/),
[fzf](https://github.com/junegunn/fzf), [chibi-cli](https://github.com/CosmicPredator/chibi-cli) (opcional).

## Licença

[MIT](LICENSE)
