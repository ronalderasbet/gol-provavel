# Gol Provável — guia de instalação (sem programar nada)

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

---

## Se algo der errado

| O que aparece | O que fazer |
|---|---|
| Bolinha vermelha na aba Actions | Clique nela, depois em "atualizar", e copie a mensagem de erro. Mande para o Claude. |
| "Free plans do not have access to this season" | O plano grátis da API-Football não liberou a temporada atual. Cadastre a chave reserva (Parte 4, passo 4). |
| O link do site dá "404" | Confira a Parte 5 e rode a Parte 6 de novo. |
| Um jogo ficou sem placar | O app tenta de novo sozinho por 7 dias. |

## Competições acompanhadas

Champions, Europa e Conference League · Premier League · LaLiga · Ligue 1 · Bundesliga · Serie A ·
Süper Lig · Liga Portugal · Eredivisie · Brasileirão Série A e B · Copa do Brasil · Libertadores ·
Sul-Americana · Argentina · Chile · Colômbia · Uruguai · Paraguai · Equador · Peru · México ·
Bolívia · Venezuela · MLS · Liga Saudita.

É uma estimativa estatística, não uma garantia. Se for apostar, aposte só o que pode perder.
