# FootPrevia — guia de instalação (sem programar nada)

Você vai fazer isto **uma vez só**, leva uns 20 minutos. Depois o app se atualiza sozinho
todo dia às 7h e às 12h, e você abre pelo ícone no celular.

---

## Parte 1 — Pegar a chave dos dados de futebol (5 min)

1. Abra **https://dashboard.api-football.com/register** e crie uma conta grátis.
2. Confirme o e-mail e entre na conta.
3. No menu, clique em **Account → My Access**. Copie o código que aparece em **API-KEY**
   e guarde num bloco de notas.

*(Opcional, mas recomendado)* Crie também uma conta grátis em **https://www.football-data.org/client/register**.
A chave chega por e-mail. Ela serve de reserva se a primeira falhar.

## Parte 2 — Criar o seu espaço no GitHub (5 min)

1. Abra **https://github.com/signup** e crie uma conta grátis (se ainda não tiver).
2. Abra **https://github.com/new**.
3. Em **Repository name**, escreva: `gol-provavel`
4. Deixe marcado **Public**. Clique em **Create repository**.

## Parte 3 — Colocar os arquivos (5 min)

1. Na página do repositório recém-criado, clique no link **uploading an existing file**.
2. Descompacte o arquivo `gol-provavel-app.zip` no seu computador.
3. Abra a pasta descompactada, selecione **as pastas `docs` e `scripts` e o arquivo `LEIA-ME.md`**,
   e arraste tudo para a página do GitHub.
4. Espere terminar de carregar e clique em **Commit changes**.
5. Agora o agendamento: clique em **Add file → Create new file**.
6. No nome do arquivo, digite exatamente: `.github/workflows/atualizar.yml`
7. Abra o arquivo `atualizar.yml` (que veio junto) num bloco de notas, copie tudo e cole na área grande.
8. Clique em **Commit changes** (duas vezes, se pedir).

## Parte 4 — Guardar as chaves com segurança (2 min)

1. No repositório, clique em **Settings** (engrenagem no topo).
2. No menu da esquerda: **Secrets and variables → Actions**.
3. Clique em **New repository secret**.
   - Name: `APIFOOTBALL_KEY`
   - Secret: cole a chave da Parte 1
   - Clique em **Add secret**.
4. Se você criou a chave reserva, repita com o nome `FOOTBALLDATA_KEY`.

## Parte 5 — Ligar o site (1 min)

1. Ainda em **Settings**, clique em **Pages** no menu da esquerda.
2. Em **Source**, escolha **GitHub Actions**.

## Parte 6 — Primeira atualização (3 min)

1. Clique na aba **Actions** (no topo do repositório).
2. Se aparecer um botão verde pedindo para habilitar, clique nele.
3. Clique em **Atualizar gol provável** na lista da esquerda.
4. Clique em **Run workflow → Run workflow**.
5. Espere a bolinha ficar verde (2 a 4 minutos).

Pronto! Seu app está em:

**https://SEU-USUARIO.github.io/gol-provavel/**

(troque SEU-USUARIO pelo seu nome de usuário do GitHub)

## Parte 7 — Instalar no celular

Abra o link acima no celular e toque em **Ajustes** (no app). Lá tem o passo a passo
para iPhone e Android, e também como ativar o botão **Atualizar** para buscar dados na hora.

## Parte 8 — Placar ao vivo e notificações (opcional, 15 min)

O placar ao vivo e as notificações dos seus times usam um pequeno serviço grátis na Cloudflare,
que confere os jogos a cada minuto. Sem ele, o app continua funcionando normalmente.

**8.1 Criar a conta e o serviço**

1. Abra **https://dash.cloudflare.com/sign-up** e crie uma conta grátis.
2. No menu da esquerda: **Compute (Workers) → Workers & Pages → Create → Create Worker** (modelo "Hello World").
3. Em **Worker name**, escreva: `gol-provavel-live`. Clique em **Deploy**.
4. Clique em **Edit code**. Apague tudo, abra o arquivo `worker.js` (veio junto) num bloco de notas,
   copie tudo e cole. Clique em **Deploy**.

**8.2 Criar o banco de dados**

1. No menu da esquerda: **Storage & Databases → D1 SQL Database → Create**.
2. Nome: `gol-provavel`. Clique em **Create**.

**8.3 Ligar tudo ao serviço** (volte em Workers & Pages → gol-provavel-live → **Settings**)

1. **Bindings → Add → D1 database**. Variable name: `DB`. Database: `gol-provavel`. **Add binding**.
2. **Variables and Secrets → Add**:
   - Type **Secret**, Name `APIFOOTBALL_KEY`, Value: a mesma chave da API-Football da Parte 1.
   - Type **Text**, Name `SITE_URL`, Value: `https://SEU-USUARIO.github.io/gol-provavel/`
   - Clique em **Deploy**.
3. **Trigger Events → Add → Cron Triggers**. Escolha **Every minute** (ou escreva `* * * * *`). **Add**.

**8.4 Avisar o app**

1. No alto da página do Worker aparece o endereço dele, algo como
   `https://gol-provavel-live.SEU-NOME.workers.dev`. Copie.
2. No GitHub: **Settings → Secrets and variables → Actions → aba Variables → New repository variable**.
   Name: `LIVE_URL`. Value: o endereço copiado. **Add variable**.
3. **Actions → Atualizar gol provável → Run workflow** e espere o ✔ verde.

**8.5 Conferir**

- No app, **Ajustes → Informações → Serviço ao vivo** deve mostrar "ativo".
- Siga um time (num jogo, "Ver todos os números" → ♡ Seguir) e toque em **Ajustes → Ativar notificações**.
  Chega uma notificação de teste.
- No iPhone, as notificações só funcionam com o app instalado na tela de início (iOS 16.4 ou mais novo).

O serviço usa a mesma cota da API-Football, só nos minutos em que há jogo das 28 competições:
em média umas 1.000 consultas por dia, bem abaixo das 7.500 do plano Pro.

---

## Se algo der errado

| O que aparece | O que fazer |
|---|---|
| Bolinha vermelha na aba Actions | Clique nela, depois em "atualizar", e copie a mensagem de erro. Mande para o Claude. |
| "Free plans do not have access to this season" | O plano grátis da API-Football não liberou a temporada atual. Cadastre a chave reserva (Parte 4, passo 4). |
| O link do site dá "404" | Confira a Parte 5 e rode a Parte 6 de novo. |
| Um jogo ficou sem placar | O app tenta de novo sozinho por 7 dias. |
| "Serviço ao vivo: com erro" em Ajustes | Confira na Cloudflare a chave `APIFOOTBALL_KEY` e o `SITE_URL` (Parte 8.3). |
| Notificação de teste não chega | Confira se as notificações do navegador estão liberadas para o site e se o celular não está em modo "não perturbe". |

## Competições acompanhadas

Champions, Europa e Conference League · Premier League · LaLiga · Ligue 1 · Bundesliga · Serie A ·
Süper Lig · Liga Portugal · Eredivisie · Brasileirão Série A e B · Copa do Brasil · Libertadores ·
Sul-Americana · Argentina · Chile · Colômbia · Uruguai · Paraguai · Equador · Peru · México ·
Bolívia · Venezuela · MLS · Liga Saudita.

É uma estimativa estatística, não uma garantia. Se for apostar, aposte só o que pode perder.
