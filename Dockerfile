FROM python:3.12-slim

# Évite que Python écrive des fichiers .pyc sur le disque
ENV PYTHONDONTWRITEBYTECODE=1

# Évite que Python mette en mémoire tampon stdout/stderr (les logs s'affichent en temps réel)
ENV PYTHONUNBUFFERED=1

# Dossier de travail dans le conteneur
WORKDIR /app

# Installation des dépendances système de base si nécessaire
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copie le fichier requirements pour mettre en cache cette étape de build
COPY requirements.txt .

# Installe les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copie le code du bot dans le conteneur
COPY bot.py .

# Commande de démarrage du conteneur
CMD ["python", "bot.py"]
