# Changelog

Todas as mudanças relevantes do USKMaker. *(English: [CHANGELOG.en.md](CHANGELOG.en.md))*

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).

Cada versão tem um instalador pronto em **[Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases)** — as notas de cada release trazem também as instruções de instalação.

## [Não lançado]

### Adicionado

- **Exportação de vídeo de karaokê (.mp4).** Uma opção nova renderiza um vídeo de karaokê a partir do pacote pronto: a letra na tela, cada sílaba preenchendo no ritmo da música, sobre a capa ou uma imagem de fundo. Traz junto um workflow do GitHub Actions que monta o instalador do Windows, para dar para testar uma alteração sem ter Rust + Node + Python instalados na máquina de quem testa.
- **Refazer o vídeo depois de corrigir o alinhamento, sem reprocessar a música.** A tela de revisão salvava os tempos corrigidos e reescrevia o `.txt`, mas deixava o `.mp4` com os tempos ANTIGOS, sem nada avisando. Aplicar um ajuste de meio segundo exigia rodar Demucs e WhisperX de novo - minutos de IA para refazer um passo que não depende de IA nenhuma. Tudo o que o vídeo precisa já está na pasta depois de uma geração, então agora ele é refeito a partir do `song_data.json` em segundos. Também disponível como `scripts/rebuild-karaoke-video.ps1`.
- **"Buscar informações" lê artista, título e duração de um link do YouTube**, antes de gerar, para conferir os campos em vez de digitá-los. A duração real da música agora também decide QUAL conjunto de letras sincronizadas usar, em vez de confiar no "melhor palpite" do LRCLIB. Inclui o `update_ytdlp.py`, que mantém o yt-dlp atualizado sozinho - ele envelhece rápido, e uma cópia velha é o motivo usual de um download começar a falhar do nada.
- **Placa de vídeo boa passa a usar o modelo de reconhecimento maior.** O "auto" lê a VRAM disponível e escolhe o `large-v3` quando há folga (6 GB ou mais), seguindo no `medium` nos outros casos. Mais precisão para quem tem GPU boa sem precisar pedir, e nenhum risco de estourar a memória de uma placa modesta - uma correção não pode piorar quem já estava funcionando.
- **As letras sincronizadas agora são encontradas automaticamente quando a primeira consulta volta sem elas.** O endpoint de "melhor palpite" do LRCLIB devolve um registro só, que às vezes não traz letra sincronizada nenhuma; agora o app cai para uma busca de verdade e escolhe um resultado cuja duração bate com a música.
- **Botão "Atualizar ferramentas de IA" no cabeçalho do app.** Atualizar as bibliotecas de IA exigia achar e rodar o `setup-sidecar.ps1` na mão. O botão reaproveita o mesmo comando do setup (o script é idempotente), transmite o log de progresso ao vivo e só aparece quando o ambiente está saudável — enquanto o ambiente estiver incompleto, o botão original "Configurar ambiente de IA" continua dando conta. Fica desabilitado enquanto uma música está sendo gerada.

- **Conferir os tempos da letra de ouvido e aprová-los como fonte principal.** A letra sincronizada do LRCLIB é o palpite de um terceiro: pode ser de outra gravação, e uma única linha dentro de um arquivo no mais correto pode simplesmente estar errada - comprovado no "Ministry - Effigy (Im Not An)" do próprio usuário, onde as linhas 1-3 e 7-34 estavam certas e as linhas 4-6 vinham cerca de quatro segundos atrasadas, ou seja, nenhum deslocamento global consertaria. A tela de revisão ganhou a tabela **Tempos da letra**: cada linha do `.lrc` do pacote ao lado do tempo que a IA de fato MEDIU naquela linha, com as divergências marcadas - as linhas que valem uma escuta são apontadas, em vez de procuradas. No Effigy ela marcou exatamente as três linhas que o usuário já tinha achado de ouvido, entre 34. Cada tempo toca a partir de um segundo antes da sua linha, e o mesmo botão para a reprodução. Os tempos corrigidos são gravados em **Salvar como aprovada**, em `%LOCALAPPDATA%\USKMaker\approved-lyrics` - fora da pasta da música de propósito: apagar ou gerar a música de novo não pode jogar fora um trabalho que alguém fez com o ouvido. Reabrir a tabela traz tudo de volta preenchido, casado pelo TEXTO da linha e não pela posição, então um `.lrc` rebuscado não desloca as correções para as linhas erradas. O arquivo também guarda a duração do áudio conferido e avisa quando outra gravação é carregada depois.
- **Uma letra aprovada manda em todo o resto do pipeline.** A partir daí, "Buscar letra" usa a versão aprovada sem consultar o LRCLIB, o aviso antes de gerar sobre a letra não caber no áudio é pulado, e o sidecar reconhece a marca de aprovação e recua: sem checagem de duração, sem piso de reconhecimento, e os inícios de linha aprovados entram como âncoras fixas por cima do que o Whisper ouviu. Todas as defesas do `align.py` existem porque o palpite de um terceiro pode ser de outra gravação; um início de linha que uma pessoa conferiu NESTA gravação não é palpite, e desconfiar dele seria trocar uma medida humana por uma heurística. Como o início de cada linha e o da linha seguinte passam a ser fatos, o passe de realinhamento só pode procurar entre os dois - não consegue mais largar uma frase nove segundos longe de onde ela é cantada, que é exatamente o que fazia antes. Medido no Effigy do usuário depois de aprovar: os 34 inícios de linha são dele, e sobra uma palavra estimada em 349.
- **"Gerar de novo" devolve uma música pronta ao formulário principal.** O formulário é limpo depois de gerar, então repetir uma música significava caçar o link do YouTube outra vez e redigitar o nome - a primeira coisa de que se precisa logo depois de aprovar os tempos corrigidos. Um botão na tela de revisão agora preenche o formulário de volta. O link não é guardado em lugar nenhum de propósito, mas o yt-dlp o imprime no log do processo, que fica na pasta do pacote, e é de lá que ele é recuperado; quando não dá (origem em arquivo local, ou auxiliares apagados) o nome é preenchido e a mensagem pede para colar o link.

- **Manter as vozes de apoio e as harmonias no karaokê.** O Demucs tira TODA voz do instrumental, harmonias inclusive - e em muita música, especialmente o synth-pop dos anos 80 para o qual isto é usado, o arranjo vocal é metade do que faz a música soar como ela é. O app já baixa um segundo modelo que distingue a voz PRINCIPAL das vozes de apoio, mas ele só servia para ajudar o alinhamento, e o stem de apoio que produzia era jogado fora. A opção nova **Manter as vozes de apoio** guarda esse stem e o soma de volta ao instrumental, de modo que só a voz principal sai. Testado numa música real antes de qualquer linha ser escrita: as harmonias voltaram sem nenhum resquício do vocalista principal, e no nível natural delas, sem precisar recuar. É opt-in, porque custa uma separação a mais, e precisa do Backtrack ligado - é ele que faz o instrumental ser o áudio do pacote. Não-fatal do começo ao fim: se a segunda separação falhar por qualquer motivo, o pacote sai com o instrumental de sempre e avisa. A mistura passa `normalize=0` de propósito - por padrão o misturador do ffmpeg divide cada entrada pelo número de entradas, o que baixaria toda música cerca de 6 dB sem ninguém pedir; conferido misturando um stem SILENCIOSO e medindo a saída exatamente no nível original. Pedido do usuário.

### Corrigido

- **A letra sincronizada era escolhida por um campo de metadado que o LRCLIB muitas vezes tem errado, e depois era jogada fora.** O app escolhia um registro comparando o `duration` declarado com a música, mas esse campo é preenchido por colaboradores e pode simplesmente ser falso. Caso real (2026-09-06, "Peter Murphy - Cuts You Up"): o registro 19409675 declara 254,8 s — batendo quase exatamente com a gravação — e carrega uma letra que vai até 5:12. O sidecar então a recusava corretamente (`lrc_duration_mismatch`) e o alinhamento seguia só com a IA; o resultado colocou 17 linhas de letra em oito segundos e deixou um buraco de 63 segundos no meio da música. Agora os candidatos são julgados pelos timestamps de DENTRO do arquivo — a última linha que de fato tem texto — com a mesma regra e as mesmas margens do sidecar, e um que cabe na gravação ganha de um cujo metadado só parece certo. Os tempos dentro do arquivo não mentem; o número ao lado dele, sim.
- **Só dava para descobrir que a letra não cabia depois de três minutos de processamento.** A checagem que a rejeita existia só no sidecar, então rodava durante o alinhamento — muito depois de ainda haver algo útil a fazer. Agora a mesma checagem roda também ao apertar Gerar, dizendo os dois tempos ("a letra sincronizada vai até 5:07, mas esta gravação tem 4:14") e deixando você parar e trocar a letra. A checagem do sidecar continua igual, como rede final.
- **A letra saía cerca de três segundos adiantada no vídeo de karaokê, em toda linha, a música inteira.** No formato de legenda ASS, as durações de karaokê são relativas ao instante em que a linha APARECE, não ao relógio da música. Como cada linha aparece antes para dar tempo de ler, o preenchimento inteiro começava adiantado exatamente esse tanto - um deslocamento constante em todas as linhas. Corrigido com a pausa idiomática `{\k}` vazia, que consome o tempo de leitura sem pintar nada. O `.txt` do jogo esteve certo o tempo todo; era só o vídeo.
- **Placas da série RTX 50 baixavam 2,5 GB de CUDA e mesmo assim rodavam na CPU.** A Blackwell (sm_120) só ganhou kernels a partir do CUDA 12.8, e o setup instalava um build cu126 fixo. O pipeline caía corretamente para a CPU em vez de quebrar, então nada parecia errado - só inexplicavelmente lento. Agora o setup lê a compute capability real da placa pelo `nvidia-smi` e escolhe o cu128 de 12.0 para cima, deixando toda placa mais antiga exatamente no caminho de antes.
- **Palavras saíam coladas no vídeo - "missyou", "beenlonelysince", "Oh,and".** Pela convenção do formato do pacote, o espaço que separa duas palavras fica grudado na ÚLTIMA nota da palavra, e essa nota pode ser uma continuação de melisma cujo texto é um til mais um espaço. Descartar a nota de continuação levava o espaço junto. O til em si é notação de pitch e nunca é exibido; o espaço ao lado dele é texto de verdade.
- **Um download do YouTube que falhava mostrava a linha de comando crua em vez do motivo.** O yt-dlp escreve a causa real numa linha `ERROR:` enterrada no meio de dezenas de outras, e o usuário recebia um `CalledProcessError` com o comando inteiro enquanto o "HTTP Error 403: Forbidden" ficava escondido na saída. Agora a mensagem real é extraída e virada em algo acionável - inclusive que um 403 costuma ser temporário e vale tentar de novo.
- **O setup podia morrer na hora para quem tem nome de usuário do Windows com duas palavras.** O passo que protege o torch entrega ao uv um arquivo de constraints guardado no `%TEMP%`, e o uv QUEBRA o valor de `--constraints` em espaços — então `C:\Users\John Smith\AppData\Local\Temp\...` chegava lá como `C:\Users\John` e a execução terminava com "File not found", derrubando o setup inteiro. MEDIDO em 2026-09-05: `-c`, `--constraints`, `--constraints=VALUE` e a variável de ambiente `UV_CONSTRAINT` quebram o valor; só o `-r` sobrevive a um caminho com espaço. Agora o setup passa o nome curto 8.3 do caminho (`C:\Users\JOHNSM~1\...`), que nunca tem espaço. Quando os nomes 8.3 estão desativados no volume, ele simplesmente não atualiza em vez de chutar — o mesmo fallback seguro que já existe quando não dá para ler a versão do torch instalado, pela mesma regra: ficar desatualizado é melhor que perder a GPU, e os dois são melhores que um setup que morre.
- **O torchcodec nunca conseguia carregar, em máquina nenhuma.** Ele vem junto do torch 2.8 e é o que o torchaudio e o pyannote usam para decodificar áudio, mas precisa das bibliotecas *compartilhadas* do FFmpeg — e o ffmpeg embutido é um executável único, autocontido, sem nenhuma biblioteca ao lado. Toda execução falhava nas quatro versões de FFmpeg que ele tenta e deixava um aviso barulhento no log. Eram duas coisas. O setup agora instala as sete bibliotecas compartilhadas do FFmpeg 7.1.1 junto do ffmpeg embutido (versão 7 de propósito: o torchcodec 0.7.0 só traz loaders para FFmpeg 4-7, e mesmo o 0.10.0 para no 8 — um build "mais recente" do FFmpeg 9 é inútil aqui). E o sidecar agora registra essa pasta com `os.add_dll_directory`, porque desde o Python 3.8 o Windows NÃO procura no PATH as dependências de uma DLL e o torchcodec só passou a cuidar disso sozinho na 0.10.0 — ou seja, as bibliotecas podiam estar na pasta certa e continuar invisíveis. São sete arquivos, não seis: o `avfilter-10` puxa o `postproc-58`, que a mensagem "or one of its dependencies" nunca diz qual é. Inofensivo enquanto os decodificadores antigos existirem; deixa de ser quando o whisperx for para o torch 2.9+ e eles sumirem.
- **Rodar o setup de novo não atualizava absolutamente nada.** As dependências são declaradas com piso (`>=`), e o `uv pip install` sem `--upgrade` só confere se o que já está instalado satisfaz o pedido, e sai — então rodar o setup de novo imprimia "Audited N packages" e deixava o usuário congelado nas versões do dia em que instalou pela primeira vez, para sempre, sem nenhum aviso de que o comando que ele rodou para "atualizar" não atualiza. Agora o setup atualiza, mas antes congela o torch instalado num arquivo de constraints: o `--upgrade` sozinho deixaria o `torch~=2.8.0` do whisperx aceitar um futuro 2.8.1 de CPU vindo do PyPI e custaria a GPU do usuário em silêncio — a mesma falha do relato do RTX 5080. Se não der para ler as versões instaladas, nada é atualizado: o comportamento anterior é o fallback seguro.
- **A mensagem de instalação do torch dizia sempre "CUDA cu126", mesmo instalando o cu128.** O rótulo era fixo e nunca olhava o índice escolhido poucas linhas acima, o que fazia a correção da RTX 50 parecer que não tinha pegado. O rótulo agora é derivado do índice escolhido, então mensagem e download não podem divergir.

- **O "Buscar dados do vídeo" comia o parêntese que fecha o nome da música.** A limpeza do título tira pontuação de sobra das duas pontas, e a lista de caracteres incluía parênteses e colchetes - então `Ministry - Effigy (Im Not An)` chegava ao formulário como `Effigy (Im Not An`, e seguia assim para a consulta ao LRCLIB, para o nome da pasta e para o `.txt` gerado. Agora um parêntese de ponta só sai quando não tem par no título, que é a cara de uma casca de verdade; `(Official Video)` e `[HD]` continuam saindo como antes. O teste que deveria cobrir isso ("Until Death (Us Do Part)") só conferia se o miolo sobrevivia, e por isso passou verdinho o tempo todo - agora compara a string inteira, e doze casos foram acrescentados em volta: com o código antigo, nove deles falham. Relatado pelo usuário. Também acrescenta a grafia britânica "Visualiser" à lista de ruído.

- **Os avisos de validação do alinhamento saíam em português com o app em inglês.** "Sobreposição entre nota 240 (fim=3024)..." - a frase era montada dentro do `rust-core`, um crate que não conhece o idioma da interface e não deveria conhecer. Agora ele devolve as sobreposições como DADOS (quais notas, em quais beats) e o app escreve a frase no idioma em uso, de modo que o texto em português continua idêntico byte a byte e quem usa em inglês finalmente lê em inglês. Relatado pelo usuário.

- **Aprovar os tempos de uma música não fazia a tabela parar de apontar as mesmas linhas.** Cinco correções digitadas, salvas e usadas - e o pacote seguinte apontava quatro das mesmas linhas. Os tempos foram aplicados certos; quem lia errado era a tabela. A coluna "A IA ouviu em" deveria ser a leitura PRÓPRIA da IA sobre onde a linha começa, mas com um tempo aprovado em uso é a ela que se DIZ onde a linha começa - leitura própria não existe mais - e a coluna caía calada na palavra SEGUINTE da linha. No "Nick Heyward - Tell Me Why (Extended Remix)" do usuário, 63 dos 65 inícios de linha vinham do arquivo aprovado, então quase toda linha podia acusar uma diferença que nunca foi divergência: "Blue eyes" mostrava "+2,5" porque é ali que a IA mediu a palavra *eyes*, 2,5 s depois do início que o usuário tinha definido. Outras duas linhas nunca teriam como sair da lista - o .lrc tem 65 linhas e o chart 63, porque as linhas de vocal de apoio entre colchetes não entram na letra, e por isso ficam em "sem par" em toda geração futura. Uma linha sobre a qual o usuário já decidiu - tempo digitado, ou ouvida e marcada como certa - agora fica RESOLVIDA e para de ser apontada, e essas marcas viajam dentro do arquivo aprovado, casadas pelo texto da linha e não pelo número dela. A diferença continua visível, e agora avisa quando o início da linha veio do arquivo aprovado em vez do áudio, porque um vão grande ali ainda pode indicar início adiantado. Relatado pelo usuário.

- **Gerar a mesma música uma segunda vez na mesma pasta morria, com os intermediários mantidos.** "Falha ao gerar o pacote: Command '[...ffmpeg.exe, -y, -i, ...video.wav, -vn, ...video.wav]'" - o mesmo caminho como entrada E saída, o que o ffmpeg recusa de saída ("cannot edit existing files in-place"). O download do vídeo grava o arquivo como `video.<ext>` e depois extrai o áudio ao lado, como `video.wav`. Numa segunda geração o yt-dlp encontra o vídeo já baixado e não mexe nele, então o `video.wav` - escrito pela geração ANTERIOR - é o `video.*` mais recente da pasta, e era ele que virava "o vídeo" de onde extrair o áudio. Só aparece quando os intermediários são mantidos, e por isso ficou escondido até o botão novo "Gerar de novo" tornar comum repetir uma música na mesma pasta. O `.wav` agora fica de fora dos candidatos: ele é o arquivo que o app escreve, não um que o yt-dlp produziu. Relatado pelo usuário.

### Alterado

- **O alarme de "reconhecimento baixo" parou de gritar à toa.** Esse aviso conta só o que o Whisper reconheceu sozinho, então não enxerga o realinhamento nem a letra sincronizada — limitação que o próprio código já registrava ("o realinhamento salva, mas o word-recall não sabe disso"). MEDIDO em 2026-09-06 em três músicas do próprio usuário, todas com reconhecimento parecido: Peter Murphy 55% com o `.lrc` RECUSADO deu 38% de palavras estimadas; Killing Joke 53% com o `.lrc` aceito deu **0%**; Ministry 59% com o `.lrc` aceito deu **0,3%**. O número do reconhecimento quase não previu a qualidade — o `.lrc` caber na gravação previu tudo — e mesmo assim as três levaram o mesmo susto vermelho. Quando o `.lrc` foi aceito, semeou inícios de linha de fato e menos de 5% das palavras ficaram estimadas, a mensagem agora é uma nota tranquila dizendo isso. O aviso vermelho continua igual em todo o resto, e esse é o ponto: um aviso que dispara em pacote bom ensina o usuário a ignorá-lo, e aí ele não vale nada no pacote quebrado.
- **Quando o reconhecimento fica ruim, a letra sincronizada passa a mandar nos inícios de linha.** Abaixo de 60% de recall medido - a fração da letra que o WhisperX de fato reconheceu, contada antes de qualquer realinhamento - o `.lrc` deixa de só preencher vãos e assume onde cada linha começa. Acima desse piso as âncoras medidas continuam ganhando, porque quando o reconhecimento está bom elas são mais precisas que qualquer arquivo externo.
- **O `scripts/setup-sidecar.ps1` passou a ser escrito em inglês** (comentários e mensagens de tela), e suas notas históricas usam datas `AAAA-MM-DD`, sem ambiguidade. Nenhum código mudou — verificado comparando o fluxo de tokens das duas versões.

## [0.20.0] — 2026-08-12

### Adicionado

- **Formato do áudio (OGG/MP3) e teto de resolução do vídeo baixado, configuráveis.** Antes o áudio de todo pacote saía sempre em OGG e o vídeo (quando incluído) baixava na melhor resolução disponível, sem limite (podia vir 4K). Agora dá pra escolher MP3 como formato — aplica em todo áudio gerado (pacote principal, faixas separadas e export YARG) — e limitar a resolução do vídeo, com **1080p como novo padrão** (quem não mexer na config passa a baixar vídeo mais leve; formato de áudio continua OGG por padrão). Pedido de usuário.
- **Notas Rap/GoldenRap na tela de revisão**, distintas de Freestyle (cantos quadrados na visualização pra diferenciar). **Botão "+ Nota" (atalho `N`)** para criar uma nota manualmente na posição do marcador de tempo, respeitando a ordem cronológica. **Piano roll lateral tocável**, sincronizado com a nota selecionada — referência de pitch durante a revisão. **Corrigido:** mover/redimensionar notas pelo teclado (setas/Shift+setas) com um grupo multi-selecionado só mexia numa nota — agora mexe no grupo inteiro, igual o arraste já fazia. Contribuição de [@mur1nu](https://github.com/mur1nu) ([PR #14](https://github.com/walterfr/UltraStarKaraokeMaker/pull/14)).

## [0.19.0] — 2026-08-08

### Adicionado

- **Trocar o tipo de nota (Normal/Golden/Freestyle) em lote, pro grupo selecionado.** Antes só dava pra mudar nota por nota. Contribuição de [@angelrdgzrivero](https://github.com/angelrdgzrivero) ([PR #13](https://github.com/walterfr/UltraStarKaraokeMaker/pull/13)).

## [0.18.5] — 2026-08-05

### Corrigido

- **GPU antiga detectada mas incompatível travava o pipeline em vez de cair pra CPU.** `resolve_device` só conferia se havia uma GPU NVIDIA com driver (`torch.cuda.is_available()`), não se o torch instalado tinha KERNEL compilado pra ela. Placas antigas (ex.: GTX 750 Ti, arquitetura Maxwell) passavam nessa checagem e só quebravam depois, dentro do Demucs, com "CUDA error: no kernel image is available for execution on the device" - sem fallback, sem aviso claro. Agora a capacidade real da GPU é comparada contra os kernels disponíveis no torch antes de escolher CUDA; se não bater, cai pra CPU (mais lento, mas funciona) com aviso no log. Relato de usuário (Vitor).

## [0.18.4] — 2026-08-04

### Corrigido

- **Download do YouTube podia pegar o áudio/vídeo de OUTRA música, em silêncio.** `download_from_youtube` escolhia "o `.wav` mais recente por data de modificação" na pasta de trabalho — se essa pasta já tivesse qualquer outro `.wav` (de um teste anterior, por exemplo), a heurística podia devolver o arquivo errado, sem erro nenhum. Resultado real (relato de usuário): letra de uma música alinhada contra o áudio de outra completamente diferente, alinhamento naufragando (0 âncora exata, 61% interpolado). Mesmo padrão corrigido no download de vídeo. Agora o nome do arquivo baixado é fixo (`audio.wav`/`video.*`), sem ambiguidade possível.

## [0.18.3] — 2026-07-31

### Corrigido

- **Setup do ambiente de IA falhava pra todo mundo desde a v0.18.0.** `requirements.txt` pedia `korean-romanizer>=1.4` — versão que nunca existiu (o pacote real nem chegou a 1.0; a mais recente é 0.28.0). Corrigido o pin. Relato de usuário (Sethid777).

## [0.18.2] — 2026-07-31

### Corrigido

- **Setup não testava a extração de pitch (`swift_f0`), só descobria a quebra na hora de gerar.** `swift_f0` importa `onnxruntime` igual o resgate de voz principal (audio-separator), mas sem proteção de try/except — se o onnxruntime dele falhar (causa comum: falta o Microsoft Visual C++ Redistributable), o sidecar inteiro morre no import, sem gerar nada. O setup validava outras bibliotecas essenciais mas não essa, então dizia "tudo certo" e o usuário só descobria o problema no meio de uma geração real (caso relatado por usuário). Agora `swift_f0` também é validado no setup, com a mesma dica de instalar o VC++ Redistributable se falhar.

## [0.18.1] — 2026-07-31

### Corrigido

- **Log de diagnóstico do sidecar podia sumir em silêncio.** O log de sessão do servidor Python era gravado dentro da pasta de instalação do app — no instalador padrão (`perMachine`, Program Files), essa pasta é só-leitura pra usuário comum, então a gravação falhava e o erro era engolido, virando `/dev/null`. Se o sidecar morresse antes de abrir o log do próprio job (ex.: crash no import do torch/CUDA, caso real com GPU antiga), não sobrava log nenhum, nem pro usuário nem pra nós. Agora esse log fica em `%LOCALAPPDATA%\USKMaker\`, sempre gravável.

## [0.18.0] — 2026-07-31

### Adicionado

- **Romanização estendida para chinês, coreano, russo, ucraniano, hindi e grego.** A opção "Romanizar" (antes só japonês/Hepburn) agora cobre mais idiomas, cada um no sistema padrão: chinês → Pinyin com tom, coreano → Revised Romanization, russo/ucraniano → transliteração cirílico→latino, hindi → IAST, grego → transliteração simples. O checkbox só aparece para idiomas com conversor disponível. Pedido de usuário.

## [0.17.0] — 2026-07-30

### Adicionado

- **Aviso visual para saltos de pitch isolados na revisão.** Em produções com camadas (ex.: harmonia de apoio uma quinta acima do vocal principal), a IA de reconhecimento de pitch às vezes trava numa nota isolada na voz errada — com alta confiança, sem se denunciar. Sem jeito barato de corrigir isso automaticamente sem processar toda música de novo, a tela de Revisão agora sinaliza essas notas (mesmo destaque visual e botão "pular pra próxima" que já existiam para outras notas suspeitas), para correção manual rápida.

## [0.16.0] — 2026-07-30

### Adicionado

- **Colar letra sincronizada (.lrc) manualmente.** A busca automática (LRCLIB) não encontra tudo — gêneros pouco indexados (ex.: EBM, industrial, darkwave) costumam ficar sem resultado. Agora dá para colar o conteúdo de um arquivo `.lrc` encontrado manualmente no site; o app extrai a letra e usa os tempos das linhas como âncoras do alinhamento, do mesmo jeito que a busca automática. Pedido de usuário.
- **Novo resgate automático: detecção de voz (VAD) mais sensível.** Quando o alinhamento sai ruim, o app agora também tenta destravar o reconhecimento de vocais baixos/atmosféricos (comum em trilhas sonoras e certos estilos eletrônicos) que a detecção de voz padrão simplesmente não percebe como canto. Só entra em ação quando o resultado já está ruim, e só fica se realmente melhorar — medido em 51 músicas de terceiros da biblioteca de teste para garantir que não piora quem já funciona bem. Relato de usuário (issue #9).

## [0.15.0] — 2026-07-30

### Corrigido

- **Letra sincronizada (LRCLIB) de gravação errada agora é detectada e ignorada.** O app busca a letra sincronizada só por artista/título, sem confirmar duração — o LRCLIB é uma base colaborativa e pode devolver a versão ao vivo, remix ou edição estendida de outra pessoa. Medido na biblioteca de teste: 66% das letras sincronizadas encontradas tinham duração incompatível com o áudio baixado. Agora, antes de usar, o app confere se a duração bate; se não bater, ignora a letra sincronizada (o alinhamento segue normal só com a IA) em vez de arriscar notas erradas.
- **Log confuso de "idioma não especificado" removido.** Em alguns casos o log mostrava um aviso de que nenhum idioma tinha sido definido, mesmo quando o usuário escolhia um na tela — o idioma escolhido sempre foi usado corretamente na transcrição, era só o aviso que estava errado. Relato de usuário (issue #9).

## [0.14.0] — 2026-07-30

### Adicionado

- **Seleção múltipla de notas na revisão.** `Shift+clique` alterna uma nota dentro/fora do grupo selecionado; `Shift+arraste` no fundo do piano roll abre um retângulo de seleção que soma as notas dentro dele ao grupo. Arrastar qualquer nota do grupo move o **bloco inteiro** (mesmo deslocamento de tempo e pitch em todas), com um único undo para o gesto. `Del` com um grupo selecionado exclui todas de uma vez. Resolve o caso de um trecho inteiro da música sair deslocado do alinhamento automático e precisar ser corrigido de uma vez, sem ajustar nota por nota. Pedido de usuário (issue #11).

## [0.13.0] — 2026-07-29

### Corrigido

- **Aviso de baixa confiança no alinhamento agora é bem mais visível.** Quando o app reconhece pouco da letra na música (ex.: vocais muito processados/eletrônicos), o pacote ainda sai, mas com risco real de estar fora de sincronia — e o aviso disso era um texto pequeno, fácil de não notar na tela de "sucesso". Agora é um banner de destaque (fundo e borda), no mesmo estilo do resto do app. Achado a partir de um relato real de usuário (vocal de música eletrônica processado, reconhecimento de apenas 18% da letra).

## [0.12.0] — 2026-07-26

### Adicionado

- **Romanizar (romaji).** Nova opção nas **Opções**, para músicas em japonês: reescreve a letra do pacote em **romaji** (alfabeto latino, sistema Hepburn), para quem não lê kana/kanji conseguir cantar. O alinhamento continua rodando sobre o japonês original — só o texto final vira romaji. Em letras que já são latinas, não muda nada.

### Corrigido

- **A instalação do ambiente de IA não trava mais por causa do resgate de voz opcional.** Antes, se o `audio-separator` (2º passe de separação, que melhora a voz em algumas músicas) não importasse — situação comum quando falta o Microsoft Visual C++ Redistributable na máquina —, o setup reprovava o ambiente **inteiro** e o app não abria, mesmo com tudo que importa funcionando. Agora esse componente é tratado como **opcional**: o setup só avisa, e o app funciona normalmente (o pipeline usa a separação do Demucs). Para reativar o resgate, basta instalar o VC++ Redistributable e rodar o setup de novo.
- **O indicador de GPU agora diz a verdade.** Antes, o app mostrava "✓ GPU" sempre que havia uma placa NVIDIA no computador — mesmo quando o PyTorch tinha caído para CPU e a geração ia rodar lenta. Agora ele checa se o PyTorch realmente enxerga a CUDA e, quando não, mostra um aviso claro ("⚠ GPU … — torch sem CUDA, rodando em CPU") em vez de um falso positivo.

## [0.11.0] — 2026-07-25

### Adicionado

- **Exportar para o YARG.** Nova opção nas **Opções**: além do pacote UltraStar, o app monta uma subpasta **"(YARG)"** pronta para o [YARG](https://yarg.in). O YARG lê o formato UltraStar `.txt` nativamente — então não há conversão de formato, só empacotamento no layout que ele espera: `notes.txt` (o mesmo chart), `song.ini` (metadados), e os áudios `song.ogg` (instrumental) e `vocals.ogg` (voz isolada), gerados a partir da separação que o app já faz. Capa (`album.jpg`) e vídeo entram quando existem. Respeita a transposição escolhida. Reaproveita tudo que o pipeline já produz, sem custo de processamento extra relevante.

## [0.10.0] — 2026-07-24

### Adicionado

- **Mudança de tom (transposição).** Novo campo **Transpor (semitons)** ao lado do BPM, de −6 a +6. O pacote sai num tom diferente do original: o app desloca o **áudio** (preservando o andamento) **e as notas** juntos, o mesmo número de semitons — tudo fica sincronizado no tom novo. Serve para compartilhar ou tocar fora do jogo já no tom certo, ou em players sem transposição ao vivo. Passos grandes (mais de ±4) degradam o áudio; combinado com o Backtrack, o resíduo da separação aparece mais. O tom é por-música: volta ao original a cada nova geração.

## [0.9.0] — 2026-07-23

### Adicionado

- **Modo backtrack (só instrumental).** Nas opções, marque **Backtrack** e o áudio do pacote sai **sem a voz-guia** — só o instrumental, para cantar por cima (karaokê de verdade). Usa a separação de voz que o app já faz na geração, então não custa tempo a mais. A qualidade é a da separação: pode sobrar um resíduo de voz aqui e ali. O alinhamento e as notas não mudam — só o áudio empacotado.

## [0.8.0] — 2026-07-23

### Adicionado

- **Botão "Gerar de novo".** Na tela de resultado, gera a mesma música outra vez sem redigitar nada. Útil quando a separação da voz sai ruim numa tentativa — ela varia a cada geração, e a próxima costuma melhorar.
- **A tela de resultado agora explica quando usar "Revisar".** Muita gente não percebia que a Revisão conserta um trecho quebrado **sem gerar de novo** — então mexer na letra e regerar acabava estragando partes que já estavam boas. Agora há uma dica no botão deixando claro: para acertar pedaços específicos, use Revisar (ajusta as notas sem re-separar a voz); regenerar é para quando a separação inteira saiu ruim.

## [0.7.1] — 2026-07-22

### Corrigido

- **O download de capa/fundo/vídeo na revisão sempre falhava** com "o download dos complementos falhou". A parte que baixa os arquivos misturava mensagens de aviso na resposta que o app lê, e isso a corrompia — não tinha a ver com o seu ambiente de IA. Corrigido; o download funciona.

## [0.7.0] — 2026-07-22

### Adicionado

- **Aviso na tela quando uma música (ou a fila) termina.** Se você deixou o USKMaker gerando e foi fazer outra coisa, o Windows te avisa quando fica pronto — `✓ Pronto: Artista - Título`, ou um resumo da fila. Só aparece quando a janela do app **não** está em foco (se você está olhando a tela, não incomoda).
- **A revisão sugere baixar capa, fundo e vídeo que faltam.** Ao escolher um pacote para revisar, o app analisa a pasta e mostra o que está faltando — com um botão para **baixar de uma vez** o que não tem (capa via MusicBrainz, fundo via fanart.tv, clipe via YouTube). Funciona também com **pacotes que não foram gerados aqui**: nesse caso o app lê o `.txt` para saber artista/título e o que já existe. *(Editar as notas continua só para pacotes gerados pelo USKMaker.)*

## [0.6.0] — 2026-07-20

### Adicionado

- **41 idiomas de música, não mais só 3.** O seletor "Idioma da música" trazia apenas português, inglês e espanhol — quem tinha música em croata, coreano, alemão, japonês etc. ficava sem opção (forçar o inglês dava resultado ruim). Agora o seletor lista os 41 idiomas que o app consegue alinhar palavra a palavra. Para idiomas de escrita não-latina (coreano, japonês, russo, árabe…), escreva a letra na escrita nativa (한국어, não romanizado) — um aviso aparece ao escolher esses. *(O motor já suportava todos; faltava a opção na tela.)*

## [0.5.1] — 2026-07-19

### Corrigido

- **Algumas músicas falhavam ao gerar com o erro `cannot access local variable 'pct'`.** Acontecia justamente com as músicas que o app alinhou **perfeitamente** (nenhuma palavra estimada) — gravações limpas. Um erro de programação fazia o app quebrar logo depois do alinhamento, ao montar os avisos de qualidade. Corrigido; essas músicas geram normalmente agora. (Bug presente desde a v0.3.8.)

## [0.5.0] — 2026-07-18

### Corrigido

- **Quando o "Configurar ambiente de IA" falhava, ele escondia o motivo.** A tela mostrava só `Traceback (most recent call last):` e parava ali — sem dizer qual biblioteca falhou nem qual foi o erro, deixando "rode de novo" como única saída. A causa era do próprio script: no PowerShell do Windows, a primeira linha de erro do Python virava uma falha fatal e o resto do diagnóstico era descartado. Agora cada biblioteca é testada em separado e, quando alguma falha, o setup diz **qual** e mostra o **fim do traceback** (onde está o erro de verdade). De quebra, um simples aviso (como o do "torchcodec") não reprova mais uma biblioteca que carregou bem.

### Alterado

- **Nova interface: a janela virou um workspace de duas colunas e não rola mais.** À esquerda ficam a música e a letra (que agora ocupa toda a altura disponível); à direita, o pacote (idioma, BPM, pasta e opções) em cartões. O botão **Gerar** fica sempre visível numa barra fixa embaixo — antes era preciso rolar a página inteira para alcançá-lo. Durante a geração, a coluna da direita mostra só o progresso; ao terminar, só o resultado. Em janelas estreitas as colunas se empilham sozinhas. As opções ganharam rótulos curtos com a explicação no tooltip, para caberem numa linha.

## [0.4.1] — 2026-07-17

### Corrigido

- **Um link do YouTube baixava a playlist inteira.** Quando o link vinha com `&list=...` (o "Mix"/rádio automático que o YouTube adiciona sozinho, ou uma playlist), o app baixava a lista inteira — você colava um clipe e recebia uma dúzia de músicas. Agora baixa só o vídeo que você escolheu.
- **Trava no alinhamento (Etapa 4) para quem não tem o ffmpeg no PATH do sistema.** A geração ia até a Etapa 4 e morria com um erro enorme (`WinError 2`, "o sistema não consegue encontrar o arquivo"). Causa: a biblioteca de alinhamento chamava o `ffmpeg` pelo nome, sem usar o ffmpeg que o app já traz embutido. Agora o ffmpeg embutido entra no caminho do processo antes do alinhamento — não é mais preciso ter ffmpeg instalado à parte. (O aviso barulhento sobre "torchcodec" que aparecia junto era inofensivo, não era a causa.)

## [0.4.0] — 2026-07-17

### Adicionado

- **Modo dueto (duas vozes).** Marque a caixa **Dueto** e diga na letra quem canta cada trecho com uma tag no início da linha — `P1:`, `P2:` ou `P1&P2:` quando cantam juntos (linha sem tag continua com o cantor da anterior). O pacote sai no formato de dueto que a comunidade usa: headers `#P1`/`#P2` (os nomes vêm do artista, ex.: "Elton John & Kiki Dee"), o corpo em dois blocos `P1`/`P2` e o sufixo `[DUET]` no arquivo. As duas vozes já estão no vocal que o app isola — o alinhamento não muda, a tag só diz de quem é cada linha. Em dueto, o resgate por voz principal isolada é pulado (ele descartaria o segundo cantor).

## [0.3.8] — 2026-07-17

### Adicionado

- **Aviso quando o app não reconhece bem a letra na música.** Havia um jeito de o pacote sair fora de sincronia sem nenhum aviso: quando o app "ouvia" outra coisa e encaixava as notas com falsa confiança, nos lugares errados. O aviso anterior só pegava o caso em que o app *não conseguia* encaixar — não o caso em que ele encaixava errado. Agora, quando o reconhecimento da letra fica baixo, a tela de resultado avisa para você conferir a sincronia (e, se estiver ruim, gerar de novo). Descoberto medindo 60 músicas contra charts feitos à mão.

## [0.3.7] — 2026-07-17

Duas melhorias na precisão das notas, as duas medidas contra 1444 charts feitos à mão.

### Alterado

- **Menos til (`~`) sobrando.** O `~` marca uma nota que sustenta e muda de altura dentro da mesma sílaba — mas o app estava exagerando: colocava `~` em três vezes mais notas que os charts feitos à mão. A causa era confundir uma nota que *escorrega* de altura (algo comum ao cantar) com uma mudança de nota de verdade. Agora a proporção de `~` está alinhada com o que os humanos fazem.

### Corrigido

- **Número na letra podia levar uma nota para o lugar errado.** Quando o app "ouvia" um número na música (ex.: "17") e a sua letra também trazia o número escrito como dígito, ele podia fixar uma nota num tempo inventado, com falsa confiança. Agora esse caso é detectado e a nota é medida do jeito certo. (Escrever o número por extenso na letra — "dezessete" — nunca foi afetado.)

## [0.3.6] — 2026-07-17

### Corrigido

- **Quem instalou nas últimas semanas provavelmente está rodando sem a GPU — e nem sabe.** A instalação baixava ~2,5 GB da versão do PyTorch com CUDA e, no passo seguinte, **trocava tudo por uma versão sem CUDA** sem avisar. O resultado: processamento na CPU (~10 min por música em vez de ~2), com o app ainda mostrando "✓ GPU". Pior: quando dava para perceber, a mensagem culpava o **driver de vídeo** — que nunca teve nada a ver. **Se você tem GPU NVIDIA, rode o Configurar ambiente de IA de novo** e confira a linha final: deve dizer `CUDA disponivel: True`.
  *(O bug apareceu sozinho, sem ninguém mexer em nada: a biblioteca que fazíamos o download passou a servir uma versão mais nova do que a que o app precisa.)*

- **Músicas que saíam completamente fora de sincronia agora se resolvem sozinhas.** A separação da voz varia a cada tentativa, e de vez em quando sai uma ruim — quando isso acontece, o app não reconhece o canto e o pacote inteiro sai errado. Agora ele detecta e **refaz a separação automaticamente**, ficando com o melhor resultado. Custa 1–3 minutos, e só nos casos em que a primeira tentativa falhou.

- **Se mesmo assim falhar, o app avisa** em vez de entregar calado. Antes, um pacote com 89% das notas estimadas trazia o mesmo aviso discreto de um com 5%.

- **Notas depois do fim da música.** Quando o alinhamento se perdia, as notas podiam ser escritas além do fim do áudio — o jogo mostrava nota sem ter o que cantar.

### Alterado

- **`#GAP` arredondado para 10 ms** (`1927` → `1930`). O valor vinha do início da primeira palavra detectada, cuja precisão real é de dezenas de milissegundos — o milissegundo ali era ruído com cara de exatidão. É a convenção da comunidade, e 10 ms está bem abaixo do que o ouvido percebe.

## [0.3.5] — 2026-07-16

### Adicionado

- **Faixas separadas de voz e instrumental no pacote** (opcional). Marcando a caixa, o pacote leva também a voz isolada e o playback, e o jogo passa a poder **controlar o volume da voz-guia separado do instrumental** — subir para aprender a música, zerar para cantar sozinho. A separação já acontecia de qualquer jeito (é como o app entende o canto); antes as faixas eram descartadas no fim. O pacote fica quase 3× maior, por isso a caixa vem desmarcada.

### Corrigido

- **O BPM manual voltou a ser literal.** Na v0.3.4 o valor digitado era ajustado junto com o automático. O campo existe para você mandar quando a detecção erra — então agora vai exatamente o que você digitou. Se o valor ficar fora da faixa que dá as notas mais precisas, o log só avisa, sem mexer no número.

## [0.3.4] — 2026-07-16

Melhorias de qualidade do chart e um bug que quebrava pacotes em silêncio. Boa parte veio de revisar os projetos vizinhos ([UltraSinger](https://github.com/rakuri255/UltraSinger), [UltraStar-Creator](https://github.com/UltraStar-Deluxe/UltraStar-Creator), [usdb_syncer](https://github.com/bohning/usdb_syncer) e a [spec oficial](https://github.com/UltraStar-Deluxe/format)).

### Corrigido

- **Título com `?`, `/` ou `:` quebrava o pacote.** Sanitizávamos o nome da pasta, mas não o dos arquivos dentro dela — e bastava um caractere comum para dar errado de três jeitos: "AC/DC" fazia o áudio ir parar em outra pasta (pacote sem som, sem erro nenhum), "Quem?" fazia a geração falhar, e "Song 2: Live" criava um arquivo de **0 byte** com o áudio escondido num *stream* do NTFS — sem reclamar. Agora os nomes seguem a mesma convenção que o USDB usa ("AC/DC" vira "AC-DC"). O título e o artista continuam intactos dentro do arquivo e nas buscas de capa/ano/gênero.
- **Notas muito mais precisas: o `#BPM` agora usa a grade fina dos charts feitos à mão.** O `#BPM` do UltraStar não é o andamento da música — é a unidade da grade de tempo. Gravávamos o andamento real, o que dava uma grade grossa demais: **59% das notas ficavam presas na duração mínima**, porque a duração real delas simplesmente não cabia. Agora a duração das notas reflete o que é cantado de verdade, e o erro de tempo por nota caiu pela metade.
- **Números na letra ("20", "1985") saíam com a nota errada.** Ninguém canta "dois-zero", canta "vinte" — e o alinhador não entende dígitos. A nota do número saía até 6× curta demais e adiantada. Agora ela acompanha o que é cantado. A letra continua escrita do seu jeito, com o número.

### Adicionado

- **Tag `#AUDIO`** no pacote, junto do `#MP3` e apontando para o mesmo arquivo. É para onde o formato está migrando: a spec já manda os players preferirem o `#AUDIO` quando ele existe, e a próxima versão do formato o torna obrigatório. Escrever os dois atende player novo e antigo.

### Nota

- O ambiente de IA ganhou uma biblioteca nova (para os números por extenso). Se você **não** rodar o **Configurar ambiente de IA** de novo, tudo continua funcionando — só a correção dos números não entra em ação.

## [0.3.3] — 2026-07-16

### Alterado

- **O Git não é mais necessário para instalar.** O `whisperx` (a biblioteca de alinhamento) era a única dependência instalada direto do repositório do GitHub (`git+https://...`), e só por causa dela o **Configurar ambiente de IA** exigia Git na máquina. Quem não tinha via o setup morrer no meio e a geração falhar depois com *"o sidecar encerrou inesperadamente"*, sem nem gerar log. Agora ele vem do PyPI, com a versão fixa (`whisperx==3.8.7rc1`) — o que também torna a instalação reproduzível, já que o `git+` seguia o último commit do repositório, um alvo móvel. É exatamente a mesma versão de antes: o pacote do PyPI foi verificado como o mesmo código, arquivo por arquivo, e confirmado com uma geração completa. Pacotes gerados não mudam.

## [0.3.2] — 2026-07-16

### Corrigido

- **O app dizia "ambiente OK" quando não estava.** Se a configuração do ambiente de IA falhasse no meio, o app mostrava o ✓ verde mesmo assim e escondia o botão de configurar; a geração então falhava com *"o sidecar encerrou inesperadamente"* e **sem gerar log** (o processo morria antes de criá-lo). Agora o app confere as bibliotecas de verdade e avisa quais faltam.
- **O setup falha de verdade quando dá errado**, em vez de terminar com mensagem de sucesso.

### Adicionado

- **Notas douradas automáticas** (`*`) nas partes sustentadas, como nos charts feitos à mão (~5% das notas, proporção calibrada medindo charts da comunidade). Antes os pacotes saíam sem nenhuma.
- **Consistência de oitava** no pitch — corrige notas isoladas em que o detector errava a oitava.

### Alterado

- **Timing bem mais preciso** — a divisão das sílabas segue a voz de verdade (em vez de dividir o tempo em partes iguais), com **melisma (`~`) real** nas sílabas sustentadas e âncoras de alinhamento mais robustas. Contribuição de [@Alejololer](https://github.com/Alejololer).
- **Resgate de voz principal** — quando o coro atrapalha o alinhamento, o app isola a voz principal e tenta de novo, só aceitando se melhorar. Contribuição de [@Alejololer](https://github.com/Alejololer).
- A tela de revisão passa a sinalizar também as notas medidas com **baixa confiança**, não só as estimadas.
- Novo módulo `eval/`: harness de avaliação de qualidade (pontuação no domínio do tempo). Contribuição de [@Alejololer](https://github.com/Alejololer).

## [0.3.1] — 2026-07-15

### Corrigido

- **O setup não abria em algumas máquinas** — o botão "Configurar ambiente de IA" falhava com um erro de caminho (`Join-Path ... o valor do argumento "drive" é nulo`) no Windows PowerShell 5.1.
- **Crash com acentos/emoji** — títulos ou tags com caracteres especiais (CJK, emoji) derrubavam o processamento no Windows. Tudo em UTF-8 agora.

### Adicionado

- **Preenchimento automático de título e artista** a partir das tags do arquivo de áudio (só os campos ainda vazios).
- **Imagem de fundo `#BACKGROUND`** no pacote: fundo 16:9 real via [fanart.tv](https://fanart.tv/get-an-api-key/) (opcional, com `FANARTTV_API_KEY`); sem a chave, reaproveita a capa — assim todo pacote com capa passa a ter fundo.
- **Correção automática de BPM** — conserta o erro comum de "meio/dobro" no andamento detectado.
- **Caixa "deixar só o essencial"** — ao fim da fila, apaga os auxiliares (`.lrc`/`.log`/`.json`) de cada pasta (opcional; remove a tela de revisão daquele pacote).
- Link discreto de apoio ao projeto na página "Sobre".

### Alterado

- Campos de **título/artista movidos para acima da busca de letra** — a busca depende deles.

## [0.3.0] — 2026-07-12

### Adicionado

- **Auto-setup do ambiente de IA por um botão.** "Configurar ambiente de IA" baixa o `uv` (que instala o Python 3.12 se você não tiver), um **ffmpeg embutido** (com libvorbis) e as bibliotecas de IA, com progresso ao vivo no app. Acabou a necessidade de instalar Python à mão, pôr o ffmpeg no PATH ou rodar o `setup-sidecar.ps1` (que segue disponível como alternativa).

## [0.2.2] — 2026-07-12

### Corrigido

- **Máquinas sem GPU NVIDIA** (ex.: Intel Iris Xe) falhavam com `AssertionError: Torch not compiled with CUDA enabled`, mesmo com a interface indicando modo CPU. O app agora detecta a ausência de CUDA e roda tudo na CPU automaticamente.

## [0.2.1] — 2026-07-12

Correções a partir de feedback da comunidade, validadas contra a [spec oficial do formato](https://github.com/UltraStar-Deluxe/format/blob/main/The%20UltraStar%20File%20Format%20(v1).md).

### Corrigido

- **Til (`~`) nas sílabas** — o `~` era prefixado em toda sílaba de continuação, e o jogo exibia o til literal na tela ("Ju~rei").
- **GAP / primeira nota** — a primeira nota agora começa no beat 0 e o atraso real do canto vai para a tag `#GAP`, então re-sincronizar com outro áudio é só ajustar o `#GAP`.
- **Mensagens de erro traduzidas** — os erros vindos do núcleo Rust passam a respeitar o idioma da interface.

## [0.2.0] — 2026-07-12

### Adicionado

- **Fila de músicas + modelos quentes** — um sidecar Python persistente mantém os modelos carregados entre músicas; da 2ª em diante o alinhamento fica bem mais rápido.
- **Buscar letra (LRCLIB)** por artista + título. Havendo versão sincronizada, os tempos de cada linha entram como âncoras no alinhamento.
- **Interface bilíngue PT/EN**, detectando o idioma do sistema.
- **Saída organizada** numa subpasta `Artista - Título` (padrão das coleções UltraStar).
- Splash, página "Sobre" e ícone nítido na barra de tarefas.

### Alterado

- **Reformulação de UX** — checagem de ambiente na abertura, validação da letra em tempo real, lista de etapas com estado e duração, cancelamento de verdade, e resultado com capa, metadados e contagem de notas medidas vs. estimadas.

## [0.1.0] — 2026-07-09

Primeira release pública: pipeline completo (letra sincronizada, pitch, BPM, metadados, vídeo), instalador Windows e setup assistido do ambiente de IA.

[0.9.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.9.0
[0.8.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.8.0
[0.7.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.7.1
[0.7.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.7.0
[0.6.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.6.0
[0.5.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.5.1
[0.5.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.5.0
[0.4.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.4.1
[0.4.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.4.0
[0.3.8]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.8
[0.3.7]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.7
[0.3.6]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.6
[0.3.5]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.5
[0.3.4]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.4
[0.3.3]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.3
[0.3.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.2
[0.3.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.1
[0.3.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.0
[0.2.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.2
[0.2.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.1
[0.2.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.0
[0.1.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.1.0
