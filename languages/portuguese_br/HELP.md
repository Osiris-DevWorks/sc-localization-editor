# Smart Citizen: Guia de Início Rápido

> Esta página é uma tradução fornecida para sua conveniência. Em caso de divergência, a versão em inglês prevalece. Status das traduções: `languages/TRANSLATIONS.md`.

## Primeira Configuração

Ao iniciar, o Smart Citizen recarrega as personalizações da sessão anterior e procura sua instalação do Star Citizen: o instalador preenche esse caminho automaticamente, mas você pode alterá-lo na aba **Config**. Toda a localização original e os dados do DataForge vêm **diretamente do seu `Data.p4k` instalado** (sem downloads, sem espelhos da comunidade), então extrair uma vez é um primeiro passo obrigatório após a instalação ou após qualquer patch do jogo.

## 1. Extrair a Localização Base do Data.p4k

Abra a aba **Config** e clique em **Extrair do Data.p4k**. Isso descompacta o `global.ini` original e os XMLs de entidades do DataForge usados pelo gerador de aprimoramentos: naves, componentes, armas, missões, blueprints etc.

Quando a extração termina, o `base.ini` extraído é carregado na tabela automaticamente, mesclado com os arquivos de aprimoramento e com as suas alterações salvas no `user.ini`.

## 2. Editar Strings de Localização

- Dê um duplo clique em qualquer célula de **Valor Personalizado** para editar o texto.
- **Valor Padrão**: texto original do `base.ini` extraído do `Data.p4k`.
- **Valor Atual**: o valor efetivo antes da sua alteração (base + camadas INI importadas).
- **Valor Personalizado**: a sua edição pessoal. Salva automaticamente a cada mudança e mantida em `<pasta de dados>\<canal>\user.ini` (a pasta de dados padrão é `Documents\Smart Citizen`, e cada canal do Star Citizen, LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW, tem suas próprias alterações isoladas).
- A coluna **Status** indica a origem do valor atual de cada linha:
  - **Modificado**: você editou explicitamente o Valor Personalizado.
  - **Aprimorado**: gerado automaticamente pelo processo de aprimoramentos (sobreposições de estatísticas, tags de blueprint etc.).
  - **Inalterado**: texto original do `base.ini`.
  - **Novo**: a chave só existe nas suas alterações ou nos aprimoramentos, não no `base.ini` original.

## 3. Painel de Pré-visualização

O **painel de pré-visualização** no canto superior direito mostra o texto renderizado da linha selecionada. Os tokens de localização do jogo são convertidos em HTML estilizado para você ver mais ou menos como a string aparecerá no jogo:

- `\n` → quebra de linha
- `<EM3>...</EM3>` → cabeçalho de seção sublinhado
- `<EM4>...</EM4>` → ênfase em azul e negrito (normalmente valores de estatísticas)
- `~mission(Name)` → marcador `[Name]` acinzentado (o jogo substitui pelo valor real em tempo de execução)

O painel fica visível em todas as abas e reflete a última linha selecionada no **Editor de Strings**: útil para conferir a formatação de uma descrição de missão longa ou de uma entrada de diário antes de aplicar.

## 4. Categorias

Use o filtro de **Categoria** para focar em um domínio:

- **Ships**: nomes e descrições de naves (`vehicle_Name*`, `vehicle_Desc*`, além das variantes Wikelo/Collector).
- **Ship Items**: escudos, usinas de energia, refrigeradores, motores quânticos, motores de salto, armas de nave, mísseis, bombas, torretas.
- **Missions**: briefings de missão, textos de contratos, descrições de recompensas.
- **Gear**: armas de FPS, armaduras, capacetes, trajes, miras.
- **Commodities**: mercadorias e materiais de fabricação.
- **Journal**: entradas de diário do jogo, estilo Galactapedia.
- **Other**: todo o resto.

## 5. Busca e Filtros

- Use a **caixa de busca** para encontrar strings por chave ou conteúdo.
- Combine com os filtros de **Categoria** e **Status** (Modificado / Aprimorado / Inalterado / Novo).
- Marque **Esconder Inalterados** para focar apenas nas suas edições.
- As **caixas de filtro por coluna** sob cada cabeçalho refinam ainda mais dentro da tabela.
- Clique em qualquer cabeçalho de coluna para ordenar. Clique no cabeçalho **★** para trazer os favoritos para o topo.

## 6. Naves Favoritas

- Clique na coluna **★** de qualquer linha de nave para marcá-la como favorita.
- Naves favoritas recebem um prefixo configurável antes do nome, fazendo-as subir ao topo da lista de naves no jogo.
- Altere o caractere de prefixo na aba **Aprimoramentos** (padrão: `*`).

## 7. Aplicar as Alterações ao Jogo

Clique em **Aplicar ao Jogo** para gravar suas edições na instalação do jogo. Um backup com data e hora do `global.ini` atual é criado em `<pasta de dados>\<canal>\backups\` antes de qualquer sobrescrita.

O Smart Citizen também carimba uma pequena marca d'água na string de versão do launcher (`Frontend_PU_Version`), acrescentando `\nLocalizations Enhanced with Smart Citizen v{VERSION}` em sua própria linha. É assim que você confirma no jogo que seu loc-pack está ativo: olhe o rótulo de versão no menu principal do Star Citizen. A marca é reescrita a cada aplicação, então nunca se acumula entre versões.

## 8. Restaurar um Backup

Abra o menu **Mais** na barra de ferramentas e escolha **Restaurar Backup** para voltar a uma versão anterior. O Smart Citizen mantém até **5 backups automáticos**; o mais antigo é removido conforme novos são criados.

## 9. Limpar a Localização

Abra o menu **Mais** e escolha **Limpar Localização** para excluir o `global.ini` personalizado do diretório do jogo, fazendo o jogo voltar ao texto padrão (original). Suas alterações salvas em `<pasta de dados>\<canal>\user.ini` ficam intactas e podem ser reaplicadas a qualquer momento.

## 10. Importar INI

Use **Importar INI** na aba **Config** (também disponível no menu **Mais** da barra de ferramentas) para incorporar um arquivo INI existente às suas alterações. Uma caixa de resolução de conflitos permite decidir, chave por chave: **manter o atual**, **usar o importado**, **anexar**, **inserir antes**, ou informar um valor **personalizado**.

## 11. Exportar Loc-Pack

Abra o menu **Mais** e escolha **Exportar INI…** para empacotar o `global.ini` atualmente aplicado em um único zip, `SmartCitizen-LocPack-{canal}-{AAAAMMDD}.zip`, que qualquer pessoa pode soltar em `StarCitizen\<canal>\data\Localization\english\` para usar o mesmo loc-pack sem instalar o Smart Citizen. Útil para compartilhar configurações com amigos ou com sua org.

## 12. Redefinir user.ini

Use **Resetar user.ini** na aba **Config** para apagar todas as suas edições pessoais do canal ativo. Uma confirmação evita cliques acidentais, e um backup automático do `user.ini` atual é feito antes em `<pasta de dados>\<canal>\backups\`: a redefinição é recuperável se você mudar de ideia.

## 13. Após Atualizações do Jogo

Quando o Star Citizen é atualizado, suas edições ficam preservadas em `<pasta de dados>\<canal>\user.ini`. Execute novamente **Extrair do Data.p4k** para puxar as strings originais do jogo atualizado: a tabela recarrega automaticamente e suas personalizações se reaplicam por cima.

## 14. Trocar de Idioma

Escolha um idioma no menu **Idioma** da aba **Config** (ao lado de Canal). A troca muda tanto a interface do app quanto as strings do jogo na tabela:

- **Inglês** (o padrão) usa as strings originais extraídas do seu próprio `Data.p4k`.
- **Outros idiomas** baixam o `global.ini` traduzido pela comunidade para aquele idioma e o sobrepõem à base em inglês: qualquer string que a tradução não cobre cai de volta para o inglês em vez de sumir. O download fica em cache por idioma; voltar a um idioma já usado reaproveita o cache.
- **Os aprimoramentos continuam em inglês.** Blocos de estatísticas, tags e detalhes de missão são gerados a partir dos dados do jogo e mantêm a forma em inglês sobre a prosa traduzida. Uma linha mista (digamos, um nome de função em português dentro de um bloco de estatísticas em inglês) é esperada, não é um bug.
- **Mapear Arquivo de Idioma** (aba Config) permite apontar um idioma para outra URL de `global.ini`, por exemplo o seu próprio fork de uma tradução da comunidade. A sua URL vence o padrão incluído.
- Alguns textos da interface só atualizam após reiniciar o app. As strings da tabela recarregam imediatamente.

Ao aplicar, o app grava na pasta de idioma correspondente da instalação do jogo e define `g_language` no `user.cfg`, para que o jogo carregue o arquivo certo.

Quer ajudar a traduzir? O status das traduções por idioma fica em `languages/TRANSLATIONS.md` no repositório, e preferimos muito mais as suas palavras do que as de uma máquina. Fale com a gente no Discord.

## Aba Aprimoramentos

- Ative sobreposições de estatísticas que acrescentam dados numéricos às descrições: velocidade SCM, HP de escudo, DPS, capacidade de carga, estatísticas de feixe de lasers de mineração (Fratura / Extração), rendimento de ferramentas de salvamento portáteis, listas de blueprints, XP de missão e mais.
- Ative ou desative cada categoria de aprimoramento de forma independente.
- Configure o caractere de prefixo das naves favoritas.
- **Criador de Tags**: personalize as tags entre colchetes colocadas nos nomes de componentes, mísseis, armas de nave e commodities. Reordene elementos com ▲/▼, desative elementos individuais, mude o tamanho da abreviação (`M` / `MIL` / `Military`), escolha o separador (nenhum, hífen, espaço etc.) e os colchetes (quadrados, redondos, nenhum etc.), e escolha se a tag aparece antes ou depois do nome. Componentes também têm um elemento **Type** opcional (Escudo, Refrigerador, Usina etc.), desativado por padrão. Clique em **Aplicar alterações nas tags** para salvar e regenerar.
- **Rótulos de Missão**: personalize os cabeçalhos de seção dos blocos de aprimoramento de missão (MISSION DETAILS, POTENTIAL BLUEPRINTS, ITEM REWARDS, BLUEPRINT DATA), o rótulo de XP exibido em missões sem rank de reputação específico (padrão "Rep") e a tag de ênfase (EM3 = sublinhado, EM4 = cor) usada nos cabeçalhos.
- **Campos dos Detalhes de Missão**: mostre ou oculte individualmente cada linha do bloco MISSION DETAILS (tipo de missão, dificuldade, spawns, reputação, blueprints e a tag de título `[BP]`), para que suas descrições de missão carreguem só os dados que importam para você.
- Clique em **Gerar Aprimoramentos** para extrair os dados do DataForge do `Data.p4k` e reconstruir os arquivos INI de aprimoramento. Os patches declarativos em `patches/` são reaplicados de forma idempotente a cada regeneração, para que os bugs de dados conhecidos da CIG continuem corrigidos sem esperar um patch do jogo.

## Aba Config

- **Aparência**: escolha o tema do app (veja abaixo).
- **Instalação do Star Citizen**: caminho para o seu diretório LIVE; detectado automaticamente na instalação, editável aqui. O menu **Canal** escolhe qual canal o app lê e grava, e o menu **Idioma** troca o app e as strings do jogo (veja *Trocar de Idioma* acima).
- **Dados do Smart Citizen**: pasta para `user.ini`, caches, extração do DataForge, INIs de aprimoramento gerados e backups. Padrão `Documents\Smart Citizen`; mova para fora do OneDrive se a extração ou a limpeza do cache estiver lenta.
- **Localização Base (Extração do P4K)**: clique em **Extrair do Data.p4k** para descompactar a localização original e os dados de entidades do DataForge diretamente do jogo instalado. Esta é a única fonte das strings base e dos dados de aprimoramento.
- **Importar INI**: incorpore um arquivo INI existente às suas alterações pela caixa de resolução de conflitos.
- **Resetar user.ini**: apague todas as suas edições pessoais do canal ativo. Pede confirmação e faz backup automático do `user.ini` atual antes de limpar.

## Aba Log

- Log da aplicação em tempo real.
- Filtre por nível, ative a rolagem automática e **exporte** o log para diagnóstico ou relatórios de bug.

## Temas

Escolha um tema em **Config → Aparência**:

- **Padrão**: SCLE, um tema cyber azul-marinho inspirado na interface mobiGlas do Star Citizen.
- **Claro / Escuro**: temas de interface clássicos.
- **ODW**: assinatura Osiris DevWorks, grafite marinho com dourado antigo.

## Barra de Status

Mostra a contagem de entradas carregadas / modificadas e o estado de qualquer tarefa em segundo plano (extração, geração, aplicação).

## Tour Guiado

Clique no botão **Tutorial** da barra de ferramentas a qualquer momento para repetir o tour guiado: um passo a passo do fluxo principal com balões apontando cada controle. O tour também roda automaticamente na primeira vez que você inicia uma nova versão, para que uma instalação nova nunca comece no escuro. Clique em **Pular** a qualquer momento para fechá-lo.

## Atalhos de Teclado

- **Ctrl+Shift+C**: copiar as linhas filtradas para a área de transferência (formato chave=valor).

## Solução de Problemas

- **Nada na tabela**: confira se **Extrair do Data.p4k** terminou e se o recarregamento pós-extração concluiu, depois verifique a aba **Log** em busca de erros de leitura.
- **Aprimoramentos vazios ou com itens faltando**: execute **Gerar Aprimoramentos** na aba Aprimoramentos; é preciso ter um cache do DataForge (clique antes em **Extrair do Data.p4k** se ainda não fez).
- **Falha ao Aplicar ao Jogo**: confirme o caminho de instalação do Star Citizen na aba **Config** e que o jogo não está em execução.
- **Dados desatualizados após um patch do jogo**: execute novamente **Extrair do Data.p4k** e depois regenere os aprimoramentos.

## Problemas Conhecidos

Algumas anomalias de texto de missão têm origem nos próprios dados do Star Citizen (referências erradas de chaves de localização nos registros de contratos da CIG). O jogo lê os contratos do próprio `Data.p4k` em tempo de execução, então o Smart Citizen não pode mudar qual chave o jogo consulta: só pode editar o *texto* de cada chave. Quando dá, contornamos esses bugs mesclando o conteúdo pretendido na chave que o jogo realmente lê.

- **Dossiê Jorrit, "Updated Power Usage Data" mostra o texto de Energy Anomaly**: CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). O contrato `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` da CIG aponta o parâmetro `Description` para `@Hockrow_FacilityDelve_P2M1_Repeat_desc` em vez do próprio `P2M4_Repeat_desc`, então os jogadores veem no jogo o texto de ambientação de Energy Anomaly do P2M1 numa missão chamada "Power Usage Data". O Smart Citizen contorna isso em dois passos, ambos declarados em `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json`:
  1. Uma edição do XML do DataForge para que nosso gerador de aprimoramentos anexe a lista correta de blueprints do P2M4 (Corbel Smolder, Geist Rogue/Whiteout) ao `P2M4_Repeat_desc`, em vez de recair na do P2M1.
  2. Um contorno de texto que acrescenta o conteúdo completo do `P2M4_Repeat_desc` (o texto de ambientação mais a própria lista de blueprints) ao final do `P2M1_Repeat_desc`, separado por um divisor rotulado. Como o jogo lê o ponteiro bugado e consulta `P2M1_Repeat_desc` para os dois contratos, o contrato P2M4 agora exibe o conteúdo pretendido. Jogadores do P2M1 veem o bloco do P2M4 como um apêndice rotulado após a própria descrição: mais ruidoso, mas os dois contratos agora mostram a lista de blueprints certa e o texto de ambientação certo.

  Quando a CIG corrigir o STARC-176797, o arquivo de patch inteiro pode ser excluído e a próxima regeneração volta a produzir descrições separadas e limpas.

## Feedback, Bugs e Votação de Recursos

- **Relate bugs, compartilhe configurações personalizadas e vote nos próximos recursos** no canal dedicado do Smart Citizen no Discord: [Discord da Osiris DevWorks, feedback e votação #smart-citizen](https://discord.com/channels/1438175448420057323/1472394204347895890) (é preciso entrar antes no servidor da Osiris DevWorks: [convite](https://discord.gg/BNzRegKZ7k)). A priorização de recursos é guiada pelas reações e votos nesse canal, então quanto mais demanda um pedido tem, mais cedo ele chega.
- Ao relatar um bug, anexe o log (aba Log → **Exportar**) e mencione a versão do Star Citizen que você está usando, para distinguirmos problemas originais de mudanças do jogo.
