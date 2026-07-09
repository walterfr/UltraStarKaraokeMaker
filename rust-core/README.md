# USKMaker — rust-core (Fase 1)

Núcleo Rust do gerador de `.txt` UltraStar. Nesta fase, é um crate
standalone (biblioteca + binário de teste), **ainda sem Tauri** — a
integração com a UI é a Fase 2 do roadmap.

## O que este crate faz

Lê o JSON intermediário exportado pelo `python-sidecar`
(`song_data.json`, gerado por `main.py` a cada rodada do pipeline) e
escreve o `.txt` final no formato oficial UltraStar — a mesma lógica que
o `pipeline/ultrastar_writer.py` do lado Python, portada para Rust.

## Setup

Requer o toolchain Rust (você já deve ter, já que o Ultimate Karaoke
Player usa Tauri + Rust). Confirme:

```powershell
cargo --version
```

## Rodando os testes

```powershell
cd "X:\Android Projetos\USKMaker\rust-core"
cargo test
```

Os testes em `tests/ultrastar_writer_test.rs` usam um fixture
(`tests/fixtures/sample_song.json`) baseado nos dados reais de teste de
"Sangue Latino" — validam pitch negativo, sílabas de continuação (`~`),
notas freestyle (`F`), marcadores de quebra de frase (`-`), detecção de
overlap, e a formatação de número (BPM) idêntica à convenção do Python.

## Testando com uma música real (comparação Python vs Rust)

1. Rode o pipeline Python normalmente (ele já exporta o `song_data.json`
   automaticamente desde a Fase 1):

   ```powershell
   cd "X:\Android Projetos\USKMaker\python-sidecar"
   .\venv\Scripts\Activate.ps1
   python main.py --file "./work/raw/Sangue latino.wav" --lyrics ".\work\lyrics_sangue_latino.txt" --title "Sangue Latino" --artist "Rita Lee" --language pt --out "./output_test" --bpm 123.05
   ```

2. Gere o `.txt` a partir do mesmo JSON, agora usando o Rust:

   ```powershell
   cd "X:\Android Projetos\USKMaker\rust-core"
   cargo run --bin uskmaker-writer -- "..\python-sidecar\output_test\song_data.json" "..\python-sidecar\output_test\Rita Lee - Sangue Latino (rust).txt"
   ```

3. Compare os dois arquivos (o gerado pelo Python e o gerado pelo Rust)
   byte-a-byte:

   ```powershell
   Compare-Object (Get-Content "..\python-sidecar\output_test\Rita Lee - Sangue Latino.txt") (Get-Content "..\python-sidecar\output_test\Rita Lee - Sangue Latino (rust).txt")
   ```

   Se não imprimir nada, os arquivos são idênticos — a portabilidade foi
   fiel. Se imprimir diferenças, elas apontam exatamente onde o Rust
   diverge da lógica Python (ótimo para depurar).

## Próximos passos (Fase 2)

Depois que a saída Rust bater 100% com a Python em pelo menos 2-3 músicas
de teste diferentes, este crate é incorporado ao `src-tauri/` do projeto
Tauri, e o Python passa a ser chamado como *sidecar* (processo filho)
pelo Rust, que assume a responsabilidade final de escrever o `.txt` — o
Python deixa de escrever o arquivo final diretamente (mantém só o
`song_data.json` como contrato de dados entre os dois lados).
