# 🤖 Finance Monitor — NERO

Un bot Telegram intelligent écrit en Python pour monitorer vos comptes **Slash Bank** et **Whop** en temps réel. Il envoie des alertes automatiques sur un canal/groupe Telegram à chaque transaction et permet de consulter les soldes et historiques via des commandes interactives.

---

## ✨ Fonctionnalités

* 🏦 **Intégration Slash Bank** : Récupération des transactions et des soldes de l'entité `WCATFM LLC`.
* 🛍️ **Intégration Whop** : Suivi des ventes en temps réel, alertes de paiements échoués et détection des clients en situation d'impayé.
* ⏱️ **Polling Automatique** : Vérification planifiée toutes les heures (personnalisable) avec déduplication stricte grâce à `seen_transactions.json`.
* 🔒 **Sécurisé** : Accès limité exclusivement au groupe Telegram autorisé via le `TELEGRAM_CHAT_ID`.
* 🐳 **Prêt pour la production** : Configuration Docker et Docker Compose complète pour un déploiement instantané sur votre VPS.

---

## 🛠️ Commandes Disponibles

Le bot répond aux commandes suivantes dans le groupe autorisé :

* 💳 `/balance` — Affiche les soldes de tous les comptes bancaires Slash et l'état de Whop.
* 💰 `/in [n]` — Affiche les $n$ derniers paiements entrants (crédits).
* 📤 `/out [n]` — Affiche les $n$ derniers paiements sortants (débits).
* 📊 `/tx [n]` — Liste les $n$ dernières transactions globales.
* 📅 `/today` — Synthèse des paiements entrants du jour et montant total accumulé.
* 📅 `/yesterday` — Synthèse des paiements entrants de la veille et total.
* ❌ `/failed` — Liste les derniers paiements en échec sur Whop.
* 🚨 `/unpaid` — Liste les paiements en échec sans relance réussie depuis 7 jours.
* 🔍 `/check` — Force une vérification manuelle immédiate.
* ℹ️ `/info` — Aide générale avec toutes les commandes.

---

## ⚙️ Configuration (`.env`)

Créez un fichier `.env` à la racine du projet en vous basant sur `.env.exemple` :

```env
# Slash Bank
SLASH_API_KEY=votre_api_key_slash
SLASH_LEGAL_ENTITY_1=id_entite_1
SLASH_LEGAL_ENTITY_2=id_entite_2
SLASH_ACCOUNT_1=id_compte_bancaire

# Whop
WHOP_API_KEY=votre_api_key_whop
WHOP_COMPANY_ID=id_compagnie_whop

# Telegram Bot
TELEGRAM_BOT_TOKEN=token_du_bot_telegram
TELEGRAM_CHAT_ID=id_du_groupe_telegram
POLL_INTERVAL_SEC=3600  # Intervalle de vérification en secondes (ex: 3600 pour 1h)
```

---

## 🐳 Déploiement Docker (Recommandé)

Le bot est entièrement conteneurisé. Pour le déployer sur votre VPS :

### Prerequis
* Docker et Docker Compose installés sur le serveur.

### 1. Préparation sur le VPS
Dans le dossier de votre projet sur le VPS :
```bash
# Créez le fichier de persistance de la base de données
touch seen_transactions.json
echo "{}" > seen_transactions.json
```

### 2. Démarrage
Lancez le bot en tâche de fond avec reconstruction automatique si le code a changé :
```bash
docker compose up -d --build
```

### 3. Gestion
* **Voir les logs en temps réel** : `docker compose logs -f`
* **Arrêter le bot** : `docker compose down`
* **Redémarrer le conteneur** : `docker-compose restart finance-bot`

---

## 🖥️ Développement Local (Sans Docker)

Si vous préférez le lancer localement sans Docker :

1. Créez un environnement virtuel et activez-le :
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```
3. Lancez le bot :
   ```bash
   python bot.py
   ```
