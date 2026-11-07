# USKMaker — `rust-core` (`uskmaker-core`)

Biblioteca em Rust compartilhada pelo backend Tauri (`src-tauri`) para leitura, validação, escrita e exportação de charts UltraStar.

## Responsabilidades

- **Escrita oficial UltraStar (`ultrastar_writer.rs`)**: converte `Song` (`song_data.json`) para o arquivo `.txt` final seguindo a especificação UltraStar Deluxe (cabeçalhos `#TITLE`, `#ARTIST`, `#BPM`, `#GAP`, `#TAGS:key:...`, `#CREATOR:USKMaker v<versão>`, blocos de dueto `P1`/`P2`, notas `:`, `*`, `F`, `R`, `G` e continuações `~`).
- **Importação de `.txt` legados e da comunidade (`Song::from_txt_str` / `Song::from_txt_file`)**: faz o parse completo de pacotes `.txt` de terceiros (mesmo sem `song_data.json`) para abertura direta na tela de Revisão e re-cálculo de pitches por IA.
- **Exportações adicionais**: geração nativa de arquivos MIDI (`.mid` com sílabas/letras embutidas) e pacotes YARG.

## Rodando os Testes

```powershell
cargo test --manifest-path rust-core/Cargo.toml
```
