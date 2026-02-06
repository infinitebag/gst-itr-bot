#!/bin/bash

echo "🚀 Setting up GST ITR BOT dev environment"

if ! command -v docker &> /dev/null
then
    echo "⚠️ Docker not installed. Install Docker Desktop first."
    exit 1
fi

if ! command -v poetry &> /dev/null
then
    echo "⚠️ Poetry not installed. Install with:"
    echo "curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

echo "📦 Installing Python dependencies..."
poetry install

echo "📁 Creating .env.local (if missing)..."
cp -n .env.example .env.local 2>/dev/null || true

echo "🐳 Starting docker services..."
docker compose up -d --build

echo "🎉 Setup complete!"
echo "Visit: http://localhost:8000/docs"