#!/bin/sh
# Entry point of the osp-api image (deploy/Dockerfile; docs/hosting.md section 7).
#
#   docker run IMAGE            osp-api serve (migrates the database, then listens)
#   docker run IMAGE init       migrate and exit (a release step)
#   docker run IMAGE <other>    run that command instead (e.g. osp-cli lab create x)
set -eu

# A PaaS (Dokku, Heroku, Appliku ...) links its database as DATABASE_URL. osp-api reads
# OSP_DATABASE_URL, and takes postgres:// / postgresql:// as they come (pg8000).
if [ -z "${OSP_DATABASE_URL:-}" ] && [ -n "${DATABASE_URL:-}" ]; then
	OSP_DATABASE_URL="$DATABASE_URL"
	export OSP_DATABASE_URL
fi

# A PaaS also says which port to listen on as PORT.
OSP_PORT="${PORT:-${OSP_PORT:-8000}}"
export OSP_PORT

case "${1:-serve}" in
serve | init) exec osp-api "$@" ;;
*) exec "$@" ;;
esac
