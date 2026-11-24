# Farol Acadêmico — academic-rag

Assistente de IA baseado em RAG para consulta a documentos por perguntas em linguagem natural.

O projeto utiliza RAG (*Retrieval-Augmented Generation*): recupera trechos dos documentos e os fornece a um modelo de linguagem para elaborar a resposta. A interface apresenta a resposta, as fontes utilizadas e o tempo de processamento.

Embeddings, busca, reordenação dos candidatos e geração são processados na infraestrutura que hospeda a aplicação. Documentos e perguntas não precisam ser enviados a uma API externa de inteligência artificial. A instituição pode escolher os documentos, o modelo e as instruções de resposta, avaliar os resultados e corrigir o processo de recuperação. Isso permite maior controle, mas não elimina imprecisões, omissões ou vieses.

## Escopo e limitações

- As respostas devem ser conferidas nas fontes, especialmente quando envolvem regras, prazos e exceções.
- Perguntas abrangentes podem recuperar apenas parte das disposições relevantes.
- A indicação de fontes não garante que todas as afirmações da resposta estejam corretas.
- Um contexto com a evidência necessária não garante que o gerador preserve todas as condições e exceções.
- Os tempos variam com o hardware, o tamanho do contexto, o carregamento dos modelos e as consultas simultâneas.
- O aviso de limite de saída indica possível resposta truncada; sua ausência não garante completude.
- A recuperação estruturada depende da qualidade do texto extraído e do reconhecimento de seus limites. Os resultados obtidos no piloto não garantem o mesmo desempenho em qualquer documento.

Este README consolida a autenticação independente, a confirmação de e-mail, a edição do próprio cadastro, a alteração de senha, a administração documental até a etapa 3 e a integração experimental da recuperação com BGE. Inclui também nome configurável e cópia da resposta.

As instruções antigas de integração com WordPress e de cadastro automático de usuários pelo login do WordPress foram substituídas.

## Arquitetura

| Componente | Função |
|---|---|
| Interface PHP | Cadastro, login, confirmação de e-mail, edição dos próprios dados e senha, consultas, catálogo e administração documental |
| API Python / FastAPI | Autenticação, validação cadastral, registro das consultas e execução do RAG |
| Sentence Transformers / `intfloat/multilingual-e5-base` | Embeddings de perguntas e documentos, com 768 dimensões |
| PostgreSQL com pgvector | Documentos, vetores, resumos, usuários, sessões e consultas |
| Recuperação estruturada em `app/rag_retrieval/` | Preparação e seleção das unidades documentais no modo BGE |
| `BAAI/bge-reranker-v2-m3` | Pontuação e reordenação dos candidatos no modo experimental |
| Ollama / Qwen3 | Geração local das respostas |
| SMTP | Envio de confirmação de e-mail |
| Worker documental Python | Extração dos PDFs, embeddings em CPU e publicação das tarefas aprovadas |

Fluxo de consulta: navegador → PHP → API Python → recuperação no PostgreSQL → montagem do contexto → geração no Ollama → resposta com fontes.

No modo BGE, a recuperação inclui a reordenação dos candidatos antes da montagem do contexto.

O terminal e a API utilizam o fluxo de consulta compartilhado. A chamada direta a `app.query` não passa pela autenticação e pelo registro de consultas do endpoint `/ask`.

O processamento local de IA não significa ausência de acesso à rede. Downloads e verificações de modelos podem acessar repositórios externos. O envio de e-mails depende da infraestrutura SMTP configurada.

## Ambiente utilizado no piloto

| Item | Configuração |
|---|---|
| Sistema operacional | Oracle Linux 9 |
| Python | 3.12, em ambiente virtual |
| Interface web | Apache, PHP 8.5 e PHP-FPM |
| Banco | PostgreSQL 15 com pgvector |
| Hardware de inferência | Dell Precision 3650, Xeon W-1350, 32 GB de RAM |
| GPU | NVIDIA GeForce RTX 3060, 12 GB de VRAM |
| Modelo de geração | `qwen3:14b` |
| Contexto / limite de saída utilizados nos testes | 4.096 / 900 tokens |
| Execução do reranker BGE na integração atual | CPU |

Esses valores descrevem o ambiente avaliado; não representam requisitos mínimos nem garantia de capacidade.

O modo BGE está integrado ao projeto, mas permanece experimental e precisa ser habilitado explicitamente. Sua presença no código não significa que esteja ativo no processo que atende à interface web.

## Organização dos arquivos

| Caminho | Conteúdo |
|---|---|
| `app/` | API, autenticação, ingestão, recuperação e geração |
| `app/rag_retrieval/` | Implementação integrada da recuperação experimental com BGE |
| `app/consultar_evidencias.py` | Consulta das evidências selecionadas, sem chamar o gerador |
| `app/sectors.py` | Códigos e validação dos setores na API |
| `web/` | Arquivos PHP de distribuição da interface |
| `web/meu-cadastro.php` | Edição dos próprios dados e alteração da senha |
| `web/sectors.php` | Relação de setores apresentada pela interface |
| `sql/` | Scripts de estrutura e migrações mantidos na versão |
| `data/` | PDFs originais, fora do diretório público |
| `data/_managed/` | PDFs publicados pela administração, com nomes internos únicos |
| `.document-jobs/` | Preparações temporárias e texto para revisão; não versionar |
| `systemd/` | Configuração do serviço documental |
| `tests/` | Testes mantidos no projeto |
| `tools/` | Ferramentas auxiliares de instalação |
| `.env.example` | Exemplo de configuração, sem credenciais reais |
| `.env` | Configuração privada da API; não versionar |
| `requirements.txt` | Dependências Python |
| `academic-env/` | Ambiente virtual local; não versionar |
| `README.md` | Documentação consolidada |
| `LICENSE.md` | Licença pública |

A pasta pública da interface pode estar em outro servidor. Copie o conteúdo de `web/` para o DocumentRoot; mantenha a configuração privada fora dele. Não publique credenciais, bases de usuários, registros de consultas, documentos restritos ou o ambiente virtual.

Pacotes e diretórios das etapas experimentais anteriores podem ser arquivados fora do projeto após conferir que não são importados pelo código ativo. A integração atual utiliza `app/rag_retrieval/`; o diretório histórico `reranker_bge_v1/` não é uma dependência dessa integração.

Relatórios locais de diagnóstico, inclusive JSONs com texto documental, devem permanecer fora do diretório público. Não os versione automaticamente junto ao código.

## Preparação do Python e do modelo

Na raiz da aplicação, crie o ambiente somente se ele ainda não existir:

```bash
python3.12 -m venv academic-env
source academic-env/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

Em instalações anteriores que utilizem `python-env`, preserve o ambiente existente e ajuste os caminhos dos comandos e do serviço. Instale uma versão do PyTorch compatível com o ambiente CUDA utilizado. Verifique:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

A autenticação utiliza `argon2-cffi`; a versão empregada na implantação foi `25.1.0`. Confirme sua presença em `requirements.txt`.

Instale o Ollama conforme a [documentação oficial](https://docs.ollama.com/) e obtenha o modelo:

```bash
ollama pull qwen3:14b
ollama list
```

Em uma instalação nova, copie `.env.example` para `.env` e preencha as opções reconhecidas por `app/config.py`. Em atualizações, preserve o `.env` existente. Configure banco, modelo, limites de contexto e saída, tempo de espera, chave da API e SMTP. Proteja o arquivo com permissões de leitura restritas ao usuário do serviço.

Para utilizar o modo BGE, disponibilize previamente os pesos do modelo na revisão esperada pela implementação. O carregamento do BGE na integração utiliza arquivos locais; não baixa automaticamente pesos ausentes.

Essa restrição do carregamento do BGE não torna todo o fluxo independente da rede: o carregamento dos embeddings pode consultar o repositório externo.

## Banco e migrações

A conexão utiliza o schema `"URX_PUBLIC"`, seguido de `public`. A coluna de embeddings deve ser `vector(768)`.

Uma instalação nova exige a estrutura-base do banco, suas sequências, triggers e tabelas de documentos e resumos. **Os scripts de autenticação e confirmação de e-mail são migrações de um banco já preparado; não constituem, sozinhos, um instalador completo.** Utilize os scripts correspondentes à versão do código.

Para uma base anterior às melhorias, a ordem documentada é:

1. Preparar a tabela `users` com as colunas `use_*` e a estrutura-base de consultas.
2. Aplicar `sql/01-autenticacao.sql`: chave estrangeira, índice de e-mail sem distinção de caixa e sessões.
3. Aplicar `sql/001_confirmacao_email.sql`: suporte à confirmação de e-mail.
4. Aplicar `sql/001_document_catalog.sql`: catálogo de documentos e arquivos originais.
5. Aplicar `sql/002_document_admin.sql`: permissão administrativa, revisão do catálogo e fila documental.
6. Aplicar a migração `20261122_meu_cadastro_setores.sql`, fornecida no diretório `sql/` do pacote de atualização cadastral: ampliação da restrição de setores para os códigos de 1 a 8.

A ordem acima segue as dependências, não apenas a ordenação dos nomes. Ajuste o caminho dos scripts conforme o local em que os pacotes foram extraídos ou incorporados ao projeto. Não reaplique migrações já instaladas para atualizar somente a interface.

Faça backup antes das migrações e interrompa o acesso durante a troca de versões incompatíveis. Execute como proprietário dos objetos ou administrador. Exemplo, ajustando host, banco e usuário:

```bash
psql -h localhost -U URX_PUBLIC -d academic_rag -W \
  -v ON_ERROR_STOP=1 -f sql/001_confirmacao_email.sql
```

A ampliação dos setores preserva os códigos existentes. A alteração do tamanho mínimo da senha para oito caracteres não exige migração do banco nem alteração dos hashes já armazenados.

Não apague usuários ou consultas para contornar falhas de integridade. Se houver transação abortada em uma sessão interativa, execute `ROLLBACK` antes de continuar.

### Usuários e setores

O cadastro atual utiliza `use_id`, `use_setor`, `use_password`, `use_cpf`, `use_email`, `use_nome_completo` e `use_ip_address`, além dos campos adicionados pela migração de confirmação. A chave de `transactions.tra_user` deve referenciar `users.use_id`.

Nome completo, e-mail, CPF, setor e senha são obrigatórios. O e-mail é normalizado para minúsculas e tem limite de 50 caracteres na estrutura atual. O CPF passa por validação de formato e dígitos verificadores, o que não comprova a identidade da pessoa.


O setor é um dado cadastral; não concede privilégios. A administração documental depende exclusivamente de `users.use_admin`, cujo padrão é `false`. O cadastro web e a edição do próprio cadastro não permitem alterar esse atributo.

A relação de setores é mantida em `app/sectors.py` e `web/sectors.php`. Alterações futuras devem manter API, interface e restrição do banco consistentes.

## Meu cadastro e senha

O usuário autenticado pode acessar **Meu cadastro e senha** a partir da tela de consultas.

A página permite:

- Consultar e alterar nome completo, e-mail, CPF e setor.
- Alterar a própria senha.
- Confirmar alterações mediante informação da senha atual.

A API identifica a conta pela sessão autenticada. O formulário não permite escolher o identificador de outro usuário nem modificar permissões administrativas.

### Alteração dos dados

Nome, e-mail, CPF e setor passam pelas validações da API. E-mail e CPF já utilizados por outra conta são rejeitados.

Alterações de nome, CPF ou setor, sem mudança efetiva do e-mail, preservam a sessão.

Quando o e-mail é alterado:

1. O novo endereço substitui o anterior no cadastro.
2. A conta volta a exigir confirmação de e-mail.
3. As sessões existentes são revogadas.
4. Os links de confirmação anteriores são invalidados.
5. É solicitado o envio de uma confirmação ao novo endereço.

O usuário precisa confirmar o novo e-mail antes de entrar novamente. Confira o endereço antes de salvar: a alteração não fica aguardando aprovação do endereço antigo.

Se houver falha SMTP após a atualização, o novo endereço permanece cadastrado e pendente de confirmação. Utilize o reenvio de confirmação após corrigir a causa da falha. Não há fila automática de envio.

### Alteração da senha

A nova senha deve:

- Ter de **8 a 128 caracteres**.
- Ser diferente da senha atual.
- Coincidir exatamente com o campo de confirmação.

A senha atual é verificada antes da gravação. Após a alteração, todas as sessões da conta são revogadas, inclusive a utilizada na operação. O usuário precisa entrar novamente com a nova senha.

A senha é armazenada como hash Argon2id. Ela não é exibida ao consultar o cadastro.

A mudança da senha por um usuário autenticado não equivale à recuperação de senha esquecida. Não há recuperação de senha documentada nesta versão.

### Endpoints cadastrais

| Método e rota | Finalidade |
|---|---|
| `POST /auth/profile` | Consultar os próprios dados |
| `POST /auth/update-profile` | Alterar os próprios dados mediante senha atual |
| `POST /auth/change-password` | Alterar a própria senha mediante senha atual e confirmação |

Essas rotas exigem `X-API-Key` e o token Bearer da sessão do usuário. A interface PHP também verifica o token CSRF dos formulários.

## Documentos e permissões

| Recurso | Usuário autenticado | Administrador (`use_admin = true`) |
|---|---|---|
| Consultar e alterar o próprio cadastro e senha | Sim | Sim |
| Alterar permissões administrativas pela interface | Não | Não |
| Fazer perguntas e conferir fontes | Sim | Sim |
| Ver títulos, nomes, tamanhos e datas dos documentos | Sim | Sim |
| Abrir e baixar PDFs publicados | Sim | Sim |
| Incluir, substituir, remover e acompanhar tarefas | Não | Sim |
| Revisar o texto e autorizar publicação | Não | Sim |

Na tela de consultas, **Consultar documentos disponíveis** abre o catálogo em outra aba, preservando a pergunta. O link de administração aparece somente para administradores. A API confere a autorização em cada operação; ocultar os botões não é o controle de segurança.

Todos os usuários autenticados podem consultar todos os documentos publicados. Não há segregação por setor ou documento. Um arquivo cadastrado, mas ausente/inconsistente no disco ou sem trechos indexados, aparece indisponível; abertura e download conferem o original.

A concessão e a revogação da permissão administrativa são feitas diretamente no banco. Exemplo, substituindo o e-mail:

```sql
UPDATE "URX_PUBLIC".users
SET use_admin = true
WHERE use_email = 'administrador@exemplo.org'
RETURNING use_id, use_nome_completo, use_admin;
```

Para revogar, use `false`. Não há tela para promover usuários. O worker também verifica a autorização do solicitante antes de preparar e publicar uma tarefa.

## Inclusão, substituição e exclusão

1. Acesse **Documentos disponíveis → Administrar documentos**.
2. Informe o título e envie um PDF, ou escolha **Substituir documento** em um item publicado.
3. Aguarde **Aguardando revisão**. O worker extrai o texto, cria trechos e gera embeddings em CPU.
4. Abra **Conferir texto**, compare com o PDF — especialmente fórmulas, tabelas e exceções — e autorize a publicação.
5. Aguarde **Concluída**. Trechos, resumo e catálogo são atualizados na mesma transação.

Na substituição, a identidade do catálogo é mantida e o documento atual continua disponível até a publicação. O arquivo pode receber outro nome. Na exclusão, digite exatamente o nome solicitado: a operação é colocada na fila, sem a etapa de revisão do texto. Não há desfazer pela interface.

A página administrativa atualiza tarefas e catálogo a cada cinco segundos. Formulários em preenchimento são preservados. Se o próprio documento em edição tiver sido substituído ou excluído, a tela informa a mudança e bloqueia o envio daquele formulário. O administrador pode conferir os dados e escolher **Descartar preenchimento e atualizar este item**, sem recarregar toda a página. O formulário de inclusão permanece intacto durante essas atualizações.

### Estados e limites

| Estado | Significado |
|---|---|
| Aguardando processamento | Upload recebido, ainda não indexado |
| Processando | Extração e geração dos embeddings |
| Aguardando revisão | Texto disponível para conferência |
| Aguardando publicação | Publicação autorizada, ou exclusão confirmada |
| Publicando | Atualização transacional em execução |
| Concluída | Operação confirmada |
| Falhou / Cancelada | Operação não concluída; conferir mensagem e logs |

- PDF de até 50 MiB, 300 páginas e 500 mil caracteres extraídos.
- Não há OCR. PDF com página sem texto extraível é recusado; a extração automática pode perder estrutura mesmo quando produz texto.
- Não há edição do texto extraído pela interface. Em caso de erro, cancele e corrija o arquivo de origem.
- O resumo publicado é um mapa extrativo de leitura; não é uma interpretação gerada pelo LLM.
- O perfil de correção de fórmulas é vinculado ao SHA-256 do PDF conferido; não é aplicado indiscriminadamente a outros arquivos.
- Uma tarefa por documento/nome pode permanecer ativa; não há processamento paralelo de várias tarefas pelo worker.
- Cancelamento disponível enquanto aguarda processamento, revisão ou publicação; não durante execução.

### Consistência e armazenamento

O PDF novo é preparado no disco antes de mudar as referências ativas. O antigo é removido após confirmar a transação. Não se mantém histórico consultável de versões. Metadados das tarefas, como nomes e situações, permanecem para diagnóstico; consultas já registradas não são reescritas.

Se houver interrupção, tarefas em processamento/publicação são marcadas como falha na retomada; as que aguardam revisão permanecem. Em falha de comunicação durante COMMIT, confira o catálogo antes de repetir: o banco pode ter confirmado a operação sem entregar a resposta ao worker. Arquivos sem referência podem permanecer em `data/_managed` para conferência manual. Não apague essa pasta em lote.

`RAG_DOCUMENTS_DIR` permite definir a pasta dos originais; `RAG_DOCUMENT_JOBS_DIR`, a pasta temporária, que deve ficar fora da pasta de originais. API e worker precisam usar o mesmo banco e configuração. Ambos os diretórios ficam fora do DocumentRoot e não devem ser publicados no repositório.

Use a administração documental para novas cargas. Os antigos comandos de ingestão e correção manual não devem ser executados simultaneamente ao fluxo da interface. A substituição global por `app.ingest --replace` deixou de ser o procedimento de atualização; não use instruções antigas para truncar os trechos.

## Consulta pelo terminal

Com o ambiente virtual ativo, banco e Ollama disponíveis:

```bash
python -m app.query \
  "Em que ano é realizada a Inspeção de Saúde regulamentar?"
```

O resultado permite conferir trechos recuperados, resposta e tempos. O uso direto desse módulo não cria automaticamente um registro em `transactions`.

O E5 utiliza `passage: ` para documentos e `query: ` para perguntas; mantenha o mesmo modelo e dimensão em toda a base.

### Seleção do modo de recuperação

| Valor de `RAG_RETRIEVAL` | Comportamento |
|---|---|
| Ausente ou `legacy` | Utiliza a recuperação anterior, mantida como padrão |
| `bge` | Utiliza a recuperação experimental integrada com reranker BGE |

Para executar uma consulta com BGE:

```bash
RAG_RETRIEVAL=bge python -m app.query \
  "Um aspirante estrangeiro pode repetir duas vezes o mesmo ano escolar?"
```

A atribuição acima vale somente para esse comando. Ela não altera o ambiente de uma API já em execução.

Para utilizar BGE na interface web, defina `RAG_RETRIEVAL=bge` no ambiente do processo que executa a API e reinicie o serviço. Para retornar ao modo anterior, defina `legacy` ou remova essa variável e reinicie novamente.

A integração não exige alterar o contrato da consulta na interface.

## Recuperação experimental com BGE

O modo BGE combina a recuperação de candidatos com a seleção de evidências estruturadas:

1. Gera o embedding da pergunta.
2. Obtém candidatos vetoriais e lexicais a partir de uma leitura consistente do banco.
3. Reconstrói unidades documentais com identificação de origem.
4. Pontua os pares pergunta/unidade com o BGE.
5. Seleciona evidências e monta o contexto dentro do orçamento estimado.
6. Entrega o contexto ao gerador configurado.

A busca lexical utiliza presença de lexemas ponderada pela raridade no corpus; não é BM25.

O BGE avalia a relevância dos candidatos. A identificação de seções, alíneas, limites e vínculos de origem é realizada pelo código de preparação documental. O reranker não faz essa separação nem interpreta, por si só, quais regras podem ser omitidas sem perda de sentido.

A seleção pode incluir uma seção inteira ou apenas unidades recuperadas. O relatório informa seleções parciais e referências normativas que exigem conferência.

A estimativa de orçamento utiliza caracteres e considera prompt, pergunta, contexto, reserva de saída e margem. **Não é uma contagem pelo tokenizer do gerador e não garante encaixe real na janela.**

Uma seleção que respeita o orçamento ainda pode ser incompleta. Referências a outras normas não são resolvidas integralmente de forma automática.

### Consulta somente das evidências

Para inspecionar a recuperação BGE sem chamar o modelo gerador:

```bash
python -m app.consultar_evidencias \
  "Quais regras do curso distinguem os aspirantes brasileiros dos estrangeiros?"
```

O comando apresenta:

- Quantidade de candidatos pontuados pelo BGE.
- Seções selecionadas e indicação de seleção integral ou parcial.
- Evidências originais e definições incluídas no contexto.
- Avisos de cobertura, referências e orçamento.
- Total estimado com reservas e tempo de processamento.

Esse comando utiliza embeddings, banco e BGE, mas não chama o gerador nem cria automaticamente um registro de consulta em `transactions`.

### Desempenho e limites observados

A integração atual executa o BGE em CPU. É esperado que essa etapa consuma CPU sem ocupar a GPU utilizada pelo Ollama.

Execuções isoladas pelo terminal incluem o carregamento dos modelos. No processo persistente da API, o modelo BGE carregado pode ser reutilizado. Isso não elimina o custo de pontuar os candidatos de cada pergunta.

Os testes do piloto mostraram melhora na localização de evidências em casos avaliados, mas não comprovaram fidelidade integral das respostas. O gerador ainda pode acrescentar consequências não explicitadas, omitir condições ou confundir regras gerais e exceções.

Por isso, a avaliação deve conferir separadamente:

- Se a evidência necessária foi recuperada.
- Se suas condições e exceções foram preservadas no contexto.
- Se a resposta afirma apenas o que as fontes sustentam.
- Se as fontes exibidas permitem conferir as afirmações.
- Se o tempo de processamento é aceitável para o uso pretendido.

O modo permanece experimental. Não há garantia de cobertura integral de uma pergunta nem de generalização para documentos com outra estrutura.

### Diagnósticos anteriores

Os experimentos com `app.diagnostico_busca`, reconstrução inicial por seções e pacotes intermediários documentam a evolução da recuperação. Eles não constituem o procedimento operacional atual.

Alguns desses scripts dependem de versões anteriores das funções de consulta e de montagem do prompt. Antes de reutilizá-los, confira sua compatibilidade com o código instalado.

Para inspecionar a recuperação integrada atual, utilize `app.consultar_evidencias`.

Os JSONs de diagnóstico podem conter texto documental e perguntas. Mantenha-os fora do diretório público e, quando forem apenas resultados locais, fora do controle de versão.

## Interface e configuração privada

A interface não depende do WordPress. Os arquivos atuais incluem:

- `index.php`, `login.php`, `logout.php` e `auth-common.php`;
- `meu-cadastro.php` e `sectors.php`;
- `confirmar-email.php` e `reenviar-confirmacao.php`;
- `documents.php` e `document-file.php` para catálogo e PDFs;
- `document-admin.php`, `document-admin-upload.php`, `document-admin-card.php` e `document-catalog.js` para administração;
- `farolete-villegagnon.png`.

Ao atualizar, publique também os novos arquivos dos quais as páginas dependem. Alterar somente a cópia em `web/` não atualiza um DocumentRoot localizado em outro diretório ou servidor.

O arquivo `farol-config.json` deve ficar fora do DocumentRoot. Exemplo:

- DocumentRoot: `/home/farol-academico/public_html`;
- configuração: `/home/farol-academico/farol-config.json`.

Também é possível indicar um caminho privado por `FAROL_CONFIG_PATH` no ambiente do PHP-FPM. Exemplo de conteúdo, com valores a substituir:

```json
{
  "api_url": "http://127.0.0.1:8000",
  "api_token": "SUBSTITUA_PELA_CHAVE_DA_API"
}
```

`api_url` é a URL-base da API, sem `/ask`.

O endereço de loopback só funciona se PHP e API estiverem no mesmo servidor e a API aceitar conexões nesse endereço. Um processo vinculado exclusivamente ao IP da rede não responde automaticamente em `127.0.0.1`.

No piloto, foi observada a API escutando em `192.168.2.210:8000`. Utilize o endereço efetivamente configurado e acessível a partir do servidor PHP.

A chave deve corresponder a `RAG_API_TOKEN` na API. O usuário do pool PHP-FPM precisa ler esse arquivo; utilize permissão `600` e proprietário apropriado.

Use HTTPS no acesso web. Se PHP e API estiverem em servidores diferentes, configure também proteção do transporte entre eles: HTTPS no navegador não cifra uma chamada HTTP feita pela interface à API.

## Autenticação e confirmação de e-mail

- Senhas de **8 a 128 caracteres** para cadastro e definição de nova senha, armazenadas como hashes Argon2id.
- Sessão PHP com cookie `Secure`, `HttpOnly` e `SameSite=Lax`.
- Token de sessão mantido no servidor PHP; somente seu hash SHA-256 fica no banco, com validade máxima de oito horas. O logout revoga o token.
- `/auth/*`, `/ask` e `/documents/*` exigem `X-API-Key`.
- Consulta, documentos e operações sobre o próprio cadastro exigem também o token Bearer do usuário.
- `/documents/admin/*` exige `use_admin`.
- `/health` permanece sem autenticação.
- Cadastro aberto, sem aprovação administrativa.
- Não há recuperação de senha esquecida documentada nesta versão.

O limitador em memória permite 20 tentativas por IP em 15 minutos nas rotas que o utilizam, incluindo cadastro, login e alterações cadastrais e de senha. Use um worker Uvicorn enquanto esse mecanismo permanecer assim. Reiniciar o processo zera os contadores; usuários sob o mesmo NAT compartilham o limite.

Novos usuários precisam confirmar o e-mail antes do primeiro login. O link vale por 24 horas, tem uso único e somente seu hash é armazenado. Abrir o link não ativa a conta: o usuário precisa pressionar **Confirmar e-mail**. A confirmação não realiza login automático.

O reenvio invalida o link anterior e possui intervalo mínimo de 60 segundos por conta, persistido no banco. A resposta de reenvio é genérica e não comprova que uma mensagem foi enviada. Falha SMTP mantém a conta pendente. Não há fila nem repetição automática do envio.

A migração inicial de confirmação preserva o acesso das contas preexistentes, sem declarar seus e-mails verificados: `use_email_confirmed_at` permanece nulo nessas contas. Essa exceção não deve ser confundida com o fluxo dos novos cadastros. Uma mudança posterior de e-mail exige confirmação do novo endereço.

### Consistência da validação de senha

O tamanho mínimo deve ser consistente entre:

- `RegisterRequest.password`, em `app/auth.py`;
- `PasswordChangeRequest.new_password`, em `app/auth.py`;
- `PasswordChangeRequest.password_confirmation`, em `app/auth.py`;
- Campos e mensagens de cadastro em `web/login.php`;
- Campos e mensagens de alteração em `web/meu-cadastro.php`;
- Mensagens de validação em `web/auth-common.php`.

Os campos usados para conferir uma senha existente não devem ser confundidos com os campos que definem uma nova senha.

Alterar o código Python no disco não atualiza automaticamente um processo já iniciado. Reinicie a API após a mudança e publique os arquivos PHP no diretório efetivamente atendido pelo servidor web.

### SMTP

Configure no ambiente da API, com valores reais mantidos fora do repositório:

```dotenv
SMTP_HOST=smtp.exemplo.org
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USER=usuario-do-servico
SMTP_PASSWORD=SUBSTITUA_PELA_SENHA
SMTP_FROM=farol@exemplo.org
```

Use remetente autorizado pelo servidor e credenciais próprias de envio. `localhost` só se aplica quando o SMTP está no mesmo host da API. O código suporta STARTTLS ou TLS desde o início, com verificação de certificado; para outras opções, confira os valores aceitos em `app/config.py`.

Aceitação pelo SMTP não garante chegada à caixa de entrada. Teste os provedores de destino. Após alterar a configuração carregada pelo serviço, reinicie a API.

## Consultas, registro e tempos de espera

A interface aceita perguntas de até 2.000 caracteres, apresenta contador e indicação de processamento. O botão de interrupção, quando disponível, encerra a espera do navegador; não garante o cancelamento da inferência nem desfaz o registro da consulta.

As consultas aceitas em `/ask` são vinculadas ao usuário autenticado e registradas antes da inferência. Uma falha posterior de geração não apaga o registro. Se a gravação falhar, a API responde HTTP 503 sem acionar o RAG. Requisições inválidas ou não autenticadas não são registradas como consultas aceitas.

`transactions` registra identificador, data/hora, usuário, IPv4 e pergunta. A estrutura documentada não armazena a resposta, o tempo de processamento ou o status final. A implementação atual utiliza IPv4; com proxy reverso, configure a resolução do IP somente para proxies confiáveis.

O contrato antigo de `/ask`, com login WordPress no corpo, não deve ser usado. Clientes HTTP precisam seguir os modelos da API atual e apresentar os dois mecanismos de autenticação descritos acima.

Os guias registram limites de 360 segundos para consultas e 90 segundos para cadastro/reenvio no PHP/cURL. A página de edição cadastral utiliza limite de 60 segundos nas chamadas de alteração. Os limites de Apache, PHP-FPM e da API precisam ser coerentes com a configuração efetiva.

Um timeout na interface não prova que o processamento no servidor foi encerrado. Em alterações cadastrais, confira o estado da conta antes de repetir uma operação cujo resultado não foi recebido.

## Serviço documental e PHP-FPM

O serviço `academic-rag-documents.service` utiliza o mesmo ambiente virtual da API e carrega a configuração por `app.config`. Se a API depender de um `EnvironmentFile` externo, configure-o também no worker. O arquivo de unidade está em `systemd/`; sua cópia versionada não substitui a instalação em `/etc/systemd/system/`.

```bash
sudo cp systemd/academic-rag-documents.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now academic-rag-documents.service
systemctl status academic-rag-documents.service --no-pager
```

O worker gera embeddings em CPU, com dois threads; o serviço fornecido limita CPU a 200% e memória a 4 GiB. Isso preserva VRAM para o Ollama, mas ainda consome recursos do servidor. O modelo pode precisar ser baixado no primeiro uso.

A etapa 3 da administração documental modificou somente interface e documentação. Essa observação não se aplica à atualização cadastral, que inclui código da API e ampliação da restrição de setores no banco.

No arquivo **do pool PHP-FPM do domínio**, os limites de upload usam esta sintaxe:

```ini
php_admin_value[upload_max_filesize] = 50M
php_admin_value[post_max_size] = 64M
php_admin_value[max_execution_time] = 180
php_admin_value[max_input_time] = 180
```

Esses valores atendem ao upload; preserve limites maiores se necessários às consultas. Confira também Apache/proxy e `request_terminate_timeout` do pool. Valide antes de recarregar o serviço PHP-FPM correspondente:

```bash
/usr/local/php85/sbin/php-fpm -t
```

A extração e os embeddings não ficam aguardando dentro da requisição web. Instalação detalhada: `INSTALACAO-documentos-etapa2.md`; atualização da interface documental: `INSTALACAO-documentos-etapa3.md`.

## Operação e validação

No ambiente do piloto, o serviço chama-se `academic-rag-api.service`:

```bash
sudo systemctl restart academic-rag-api.service
sudo systemctl status academic-rag-api.service --no-pager
journalctl -u academic-rag-api.service -n 80 --no-pager
journalctl -u academic-rag-documents.service -n 80 --no-pager
ollama ps
nvidia-smi
```

Ajuste o serviço para usar o ambiente virtual e o diretório corretos. Após editar a unidade systemd, execute `sudo systemctl daemon-reload` antes de reiniciar. Caso o OPcache não verifique alterações, recarregue o PHP-FPM correspondente.

Para conferir o endereço em que a API está escutando:

```bash
ss -ltnp | grep ':8000'
```

### Validação de sintaxe

Na raiz do projeto:

```bash
python -m py_compile \
  app/api.py \
  app/db.py \
  app/auth.py \
  app/config.py \
  app/email_verification.py \
  app/sectors.py \
  app/query.py \
  app/consultar_evidencias.py
```

No diretório público da interface:

```bash
php -l index.php
php -l auth-common.php
php -l login.php
php -l logout.php
php -l meu-cadastro.php
php -l sectors.php
php -l confirmar-email.php
php -l reenviar-confirmacao.php
```

Execute os comandos PHP usando o executável da versão que atende o site. No piloto, ele fica em `/usr/local/php85/bin/php`.

A validação de sintaxe não substitui testes de comportamento, banco, autenticação ou geração.

### Verificação funcional

Antes de disponibilizar uma atualização, confira:

1. Cadastro válido, rejeição de duplicidade, CPF inválido e confirmação de senha divergente.
2. Aceitação de senha com oito caracteres e rejeição de senha nova abaixo desse limite.
3. Bloqueio de login antes da confirmação, entrega real do e-mail e ativação pelo botão.
4. Rejeição de link expirado ou já usado e invalidação do anterior após reenvio.
5. Login, consulta, fontes, registro do usuário e logout com revogação.
6. Edição do próprio nome, CPF e setor, incluindo os novos setores.
7. Rejeição de alteração cadastral ou de senha quando a senha atual está incorreta.
8. Rejeição de nova senha igual à atual ou diferente da confirmação.
9. Alteração de senha com encerramento das sessões e novo login somente com a senha atualizada.
10. Alteração de e-mail com encerramento das sessões e exigência de confirmação do novo endereço.
11. Rejeição de tentativa de alterar identificador ou permissão administrativa pelo formulário ou pela API cadastral.
12. Respostas às perguntas de referência sobre IS, duração dos ciclos, GC4 e regras para estrangeiros.
13. Recuperação de evidências e resposta final avaliadas separadamente no modo BGE.
14. Comportamento em falha SMTP, timeout e limite de saída.
15. Conta comum: catálogo, abertura e download permitidos; administração negada.
16. Administrador: incluir, revisar, publicar, substituir e excluir um PDF de teste.
17. Atualização automática do catálogo sem perder título digitado ou arquivo selecionado.
18. Documento alterado durante edição: aviso, preservação do preenchimento e bloqueio de envio obsoleto.

Para conferir os registros:

```sql
SELECT t.tra_id, t.tra_dt, u.use_id, u.use_nome_completo,
       t.tra_ip_address, t.tra_request
FROM "URX_PUBLIC".transactions t
LEFT JOIN "URX_PUBLIC".users u ON u.use_id = t.tra_user
ORDER BY t.tra_id DESC
LIMIT 10;
```

A etapa 2 inclui 16 testes isolados em `tests/test_document_admin.py`, aprovados também no ambiente do piloto. Banco e embeddings são simulados; isso não substitui a validação integrada.

O teste de navegador da etapa 3 está em `tests/test_document_catalog_ui.cjs` e requer Node.js, Playwright e Chromium apenas no ambiente de testes. Eles não são dependências de execução do Farol.

Os pacotes de integração BGE e de edição cadastral possuem testes e instruções próprios. Caso esses pacotes tenham sido arquivados fora do projeto, consulte seus diretórios de testes e seus documentos de validação no local de arquivamento. Resultados anteriores não comprovam automaticamente alterações posteriores.

Na reversão, não restaure e libere uma versão que permita login sem confirmação enquanto houver contas pendentes. Mantenha backups fora da pasta pública e não registre senhas, tokens ou corpos de requisições de autenticação em logs.

## Nome da aplicação

Defina no `.env` privado da API:

```dotenv
APP_NAME="Farol Acadêmico"
```

Aceita até 120 caracteres imprimíveis. Espaços consecutivos são normalizados; valor ausente ou vazio usa `Farol Acadêmico`. Reinicie `academic-rag-api.service` após mudar esse parâmetro. O título da API e os assuntos/corpos dos e-mails de confirmação usam o mesmo nome.

O PHP obtém somente `app_name` pelo endpoint `POST /app/config`, protegido pela chave `X-API-Key` já usada na comunicação entre PHP e API. Não exige sessão de usuário, pois também atende ao login e cadastro. O `.env` continua apenas no servidor da API; não o copie para o servidor web nem para o diretório público.

O nome é guardado na sessão PHP por 60 segundos. Depois desse prazo, recarregue a página para refletir uma alteração. Se a API estiver indisponível, mantém o último nome conhecido ou o padrão, com até dois segundos de espera por tentativa.

O nome é escapado antes de ser exibido em HTML. O endereço e nome do remetente SMTP continuam sob controle de `SMTP_FROM`.

Esta opção muda o nome apresentado ao usuário. Caminhos, serviços systemd, nomes de cookies, imagem do farol, domínio, autoria e licença são independentes.

## Copiar resposta

O botão com ícone ao lado de **Resposta** copia somente o texto da resposta, com quebras de linha e eventuais marcadores Markdown literais. Fontes e tempo não são incluídos.

Requer JavaScript e permissão de clipboard no navegador, normalmente em HTTPS. Se a cópia falhar, a interface seleciona o texto e informa como copiá-lo manualmente. Não há bibliotecas de interface adicionais.

O teste isolado dessa funcionalidade, quando mantido na árvore de testes, pode ser executado com:

```bash
node tests/test_answer_copy.cjs
```

Ele simula DOM e permissões; a validação final deve ser feita também no navegador.

## Autoria, Uranux e licença

**Autor e licenciante do código original:** Almir de Oliveira Duarte Junior.  
**Projeto associado à Uranux:** https://uranux.com.br/

O código original é disponibilizado sob a **PolyForm Internal Use License 1.0.0**, reproduzida integralmente em [LICENSE.md](LICENSE.md). Ela permite uso e adaptações para operações internas, inclusive de organizações privadas; não concede redistribuição ou sublicenciamento. O projeto tem código-fonte disponível sob licença restritiva e não é apresentado como software livre.

Licenciamento para redistribuição, oferta a terceiros e outras permissões pode ser negociado por intermédio da Uranux, com concessão pelo titular ou por representante autorizado. A associação do projeto à Uranux não constitui, por si só, cessão de direitos patrimoniais.

Organizações da Marinha podem utilizar a licença pública para suas operações internas. Uma autorização institucional complementar poderá disciplinar expressamente compartilhamento entre organizações e hospedagem centralizada; este README não concede essa autorização adicional.

Bibliotecas, modelos, documentos e demais componentes de terceiros permanecem sujeitos às respectivas licenças e direitos. A licença do código não concede direitos sobre os documentos ingeridos, dados pessoais, marcas ou imagens de terceiros.
