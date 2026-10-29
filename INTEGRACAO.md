# Integração de evidências do projeto

Arquivos entregues:

- `scenario_project_evidence.py`: novo leitor somente de leitura para `nodes.csv` e arquivos em `data/`.
- `scenario_agent_openai.patch`: alteração mínima do `scenario_agent_openai.py` enviado na conversa.

## Aplicação

1. Copie `scenario_project_evidence.py` para o mesmo diretório Python em que está `scenario_agent_openai.py`.
2. Aplique o patch no `scenario_agent_openai.py` correspondente ao código enviado na conversa. Ele importa o coletor e injeta `project_evidence` em `_application_context()`.
3. Reinicie o kernel do notebook e reinicialize o agente.

O componente extrai somente chaves técnicas literais reconhecidas; não adivinha aliases nem converte documentação não suportada em parâmetros. CSV/TSV/TXT, JSON, TOML e alguns formatos de texto são lidos de forma limitada. PDF, DOCX, XLSX, KML, KMZ e GeoJSON são inventariados, mas ainda não têm extração semântica implementada.

A saída é evidência para o LLM, não uma atualização automática do cenário. Os valores continuam sujeitos à validação e à confirmação explícita existentes. O `nodes.csv` e os arquivos em `data/` não são modificados.
