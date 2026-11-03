#!/bin/sh
set -eu

echo "applying my-exam database schema"
npm run db:setup

echo "starting Next.js"
exec npm start
