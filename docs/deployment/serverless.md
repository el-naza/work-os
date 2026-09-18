# Serverless deployment (Vercel + Netlify)

This repository is a monorepo. It contains three browser applications, a
Django API, and a stateful WebSocket/collaboration server:

| Component    | Recommended hosting                          | Why                                                                      |
| ------------ | -------------------------------------------- | ------------------------------------------------------------------------ |
| `apps/web`   | Vercel or Netlify                            | React Router SPA/static output                                           |
| `apps/admin` | Vercel or Netlify                            | React Router SPA/static output                                           |
| `apps/space` | Vercel or Netlify                            | Static output when `VITE_STATIC_DEPLOY=1`; Docker keeps SSR by default   |
| `apps/api`   | Vercel Python Functions, or a container host | Django WSGI API; Vercel adapter is included                              |
| `apps/live`  | A long-running Node/Docker service           | Hocuspocus uses WebSockets and cannot run as a normal serverless request |
| Celery worker/beat | Northflank Sandbox or Oracle Always Free VM | Queue consumers and scheduled tasks need long-lived processes             |
| Postgres     | Neon Free or Supabase Free                   | Durable relational data and Django migrations                            |
| Redis        | Upstash Redis Free                           | Sessions, cache, throttles, and magic-link state                         |
| Uploads      | Cloudflare R2                                | Persistent S3-compatible object storage                                  |
| Email        | Resend Free or another SMTP relay            | Passwords, invitations, and notifications                                |

The practical result is **hybrid serverless**, not a single all-serverless
application. Vercel/Netlify can serve the browser bundles and short-lived HTTP
requests; they cannot keep a Celery worker, a WebSocket process, or a writable
filesystem alive.

Netlify's native Functions runtime currently supports TypeScript, JavaScript,
and Go, not a Django/Python WSGI application. Therefore the Netlify option in
this guide means **Netlify for the static frontends plus Vercel (or a container
host) for `apps/api`**. I have not added a misleading JavaScript proxy that
would still leave Django, Postgres, Redis, uploads, and authentication running
somewhere else.

## What is already in this branch

- Root `vercel.json` deploys `apps/web` from the monorepo.
- Root `netlify.toml` deploys `apps/web` from the monorepo.
- `apps/api/api/index.py` is a Vercel WSGI entry point with warm-invocation
  database connection cleanup.
- `apps/api/plane/settings/serverless.py` uses zero-age database connections,
  Redis, R2, and inline Celery tasks by default.
- `apps/api/vercel.json`, `apps/api/vercel-build.sh`, and the Vercel entrypoint
  declaration collect Django static files and let Vercel's Django preset route
  all API paths to the Python function.
- `apps/api/bin/migrate-serverless.sh` runs the Django migrations against the
  provider's direct Postgres connection.
- SPA fallback files are included for all three browser applications.
- `apps/space` uses a client loader in static mode. Its default Docker build can
  still use SSR, while `VITE_STATIC_DEPLOY=1` makes it deployable as a static
  site. Per-anchor social metadata is resolved after the SPA hydrates in that
  mode.
- Vercel and Netlify templates for the admin and public-space sites are in
  `deployments/vercel/` and `deployments/netlify/`.

## Recommended topology

Use separate subdomains. It avoids base-path collisions and makes each static
site independently deployable:

```text
app.example.com       -> Vercel or Netlify, apps/web
admin.example.com     -> Vercel or Netlify, apps/admin
spaces.example.com    -> Vercel or Netlify, apps/space
api.example.com       -> Vercel Python Function, apps/api
live.example.com      -> Render/Fly/Railway/container host, apps/live
```

Set `VITE_API_BASE_URL` to `https://api.example.com` **without** `/api` and
set the other `VITE_*_BASE_URL` values to their corresponding origin. The
frontend already appends `/api`, `/auth`, and `/api/public` where needed.

## 1. Create the free-tier services

Free tiers and limits change. Confirm the current limits before putting real
customer data on them.

### Postgres: Neon (recommended)

1. Create a Neon project in a region close to the Vercel API function.
2. Create/copy both connection strings:
   - **Pooled** connection: set this as `DATABASE_URL` on Vercel.
   - **Direct/unpooled** connection: set this locally as `DIRECT_DATABASE_URL`
     for migrations only.
3. Keep `sslmode=require` in both URLs.
4. Neon Free currently advertises 0.5 GB storage and 100 compute-hours per
   project per month. The database can suspend when idle, so the first request
   after inactivity may be slower.

Supabase Postgres is a reasonable alternative. The Django API still owns
authentication and migrations; do not enable Supabase Auth just for this
installation unless we intentionally redesign the authentication layer.

### Redis: Upstash

1. Create one Redis database.
2. Copy its `rediss://...` connection string into `REDIS_URL`.
3. The Free Redis plan currently lists 256 MB of data and 500,000 commands per
   month. Keep cache keys and file contents out of Redis.
4. Leave `SERVERLESS_INLINE_TASKS=1` for the first deployment. That avoids
   requiring RabbitMQ/Celery infrastructure, but it means a request performs
   small background work before it returns. Large exports and scheduled cleanup
   are not a good fit for this mode.

### Object storage: Cloudflare R2

1. Create a private bucket named, for example, `plane-uploads`.
2. Create an R2 API token scoped to that bucket with object read/write access.
3. Set:

   ```text
   USE_MINIO=0
   AWS_REGION=auto
   AWS_S3_BUCKET_NAME=plane-uploads
   AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
   AWS_ACCESS_KEY_ID=<R2 access key>
   AWS_SECRET_ACCESS_KEY=<R2 secret>
   ```

4. Configure bucket CORS for the browser origins that upload files. Allow the
   methods and headers used by the generated presigned POST (at minimum
   `POST`, `PUT`, `GET`, `HEAD`, `Content-Type`, and `Origin`). Keep the bucket
   private; Plane generates signed access/upload URLs.

R2's current Standard free allowance is 10 GB-month of storage, 1 million
Class A requests, 10 million Class B requests, and free Internet egress.

### Transactional email: Resend

Create and verify a sending domain, then use its SMTP relay:

```text
EMAIL_HOST=smtp.resend.com
EMAIL_PORT=587
EMAIL_HOST_USER=resend
EMAIL_HOST_PASSWORD=re_...
EMAIL_USE_TLS=1
EMAIL_USE_SSL=0
EMAIL_FROM=Plane <noreply@example.com>
```

The current Resend Free plan lists 3,000 emails/month and a 100-email/day
limit. Without SMTP, password reset, magic-link, and invitation flows will not
be usable in production.

## 2. Run migrations once

Do not run migrations on every cold start. From a local checkout with Python
3.12 and the API dependencies installed:

```bash
cd apps/api
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

export DIRECT_DATABASE_URL='postgresql://...direct...?...sslmode=require'
export DATABASE_URL="$DIRECT_DATABASE_URL"
export REDIS_URL='rediss://...'
./bin/migrate-serverless.sh

# Create the first admin interactively if this instance needs one.
python manage.py createsuperuser
```

`migrate-serverless.sh` uses `DIRECT_DATABASE_URL` if present. The deployed
function should use the provider's pooled `DATABASE_URL` instead.

## 3. Deploy the API to Vercel

Create a **separate Vercel project** for the API; do not combine the Python
function with the static web project.

1. Import the repository into Vercel.
2. Set the project Root Directory to `apps/api`.
3. Keep the included `apps/api/vercel.json`.
4. Add the variables from `apps/api/.env.serverless.example` to the Vercel
   Production environment. At minimum:

   ```text
   DJANGO_SETTINGS_MODULE=plane.settings.serverless
   SECRET_KEY=<one stable random secret>
   ALLOWED_HOSTS=api.example.com
   CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com,https://spaces.example.com
   DATABASE_URL=<pooled Neon URL>
   REDIS_URL=<Upstash rediss URL>
   AWS_ACCESS_KEY_ID=<R2 key>
   AWS_SECRET_ACCESS_KEY=<R2 secret>
   AWS_S3_BUCKET_NAME=plane-uploads
   AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
   USE_MINIO=0
   WEB_URL=https://app.example.com
   APP_BASE_URL=https://app.example.com
   ADMIN_BASE_URL=https://admin.example.com
   SPACE_BASE_URL=https://spaces.example.com
   ```

5. Deploy and check `https://api.example.com/`. The existing Django health
   response returns `{"status":"OK"}`.
6. Set `DIRECT_DATABASE_URL` locally or as a temporary Vercel variable only
   when running the migration command. It is not needed by ordinary requests.

The native Vercel Python runtime supports WSGI/ASGI applications such as
Django. The included function is still subject to serverless limits: cold
starts, request duration, connection limits, and a read-only filesystem except
for `/tmp`.

## 4. Deploy the browser apps

### Web app

The root files are ready:

- Vercel: create a project with the repository root as the project directory;
  `vercel.json` selects `apps/web`.
- Netlify: create a site from the repository; `netlify.toml` selects
  `apps/web`.

Set these build-time variables on either provider:

```text
VITE_API_BASE_URL=https://api.example.com
VITE_WEB_BASE_URL=https://app.example.com
VITE_ADMIN_BASE_URL=https://admin.example.com
VITE_ADMIN_BASE_PATH=/
VITE_SPACE_BASE_URL=https://spaces.example.com
VITE_SPACE_BASE_PATH=/
VITE_LIVE_BASE_URL=https://live.example.com
VITE_LIVE_BASE_PATH=/live
```

### Admin and public space

Create separate sites so each gets its own domain. Use the corresponding
configuration as the site's build configuration:

- Vercel: copy `deployments/vercel/admin.json` or `space.json` to the project
  config, or use the same commands/output directory in the Vercel dashboard.
- Netlify: copy `deployments/netlify/admin.toml` or `space.toml` to the root as
  `netlify.toml`, or select the file as the site's configuration file.

The important build settings are:

```text
Admin command:  pnpm turbo run build --filter=admin...
Admin publish:  apps/admin/build/client
Admin base:     VITE_ADMIN_BASE_PATH=/

Space command:  VITE_STATIC_DEPLOY=1 pnpm turbo run build --filter=space...
Space publish:  apps/space/build/client
Space base:     VITE_SPACE_BASE_PATH=/
```

Supply the same `VITE_API_BASE_URL`, `VITE_WEB_BASE_URL`,
`VITE_SPACE_BASE_URL`, `VITE_ADMIN_BASE_URL`, and `VITE_LIVE_BASE_URL` values
as for the web app. These variables are embedded into the browser bundle at
build time; changing them requires a rebuild.

## 5. Run the Celery worker and beat process

The API function can enqueue work, but it cannot keep a Celery process alive.
Run two long-lived commands outside Vercel:

```text
./bin/docker-entrypoint-worker.sh  -> celery -A plane worker -l info
./bin/docker-entrypoint-beat.sh    -> celery -A plane beat -l info
```

Set `SERVERLESS_INLINE_TASKS=0` on the Vercel API once these processes are
running. Otherwise the serverless API executes tasks inside the request and the
external worker will have nothing to consume. The worker and beat process should
share the same Postgres database, Redis broker, R2 credentials, and stable
`SECRET_KEY` as the API.

### Easiest no-cost option: Northflank Sandbox

Northflank's current Sandbox tier advertises two free services with always-on
compute. That maps neatly to one `plane-worker` service and one `plane-beat`
service. Create both from this repository using `apps/api/Dockerfile.api` with
`apps/api` as the Docker build context:

| Service      | Start command                              | Public port |
| ------------ | ------------------------------------------ | ----------- |
| `plane-worker` | `./bin/docker-entrypoint-worker.sh`       | None        |
| `plane-beat`   | `./bin/docker-entrypoint-beat.sh`         | None        |

Use the worker/background-service type if the dashboard offers it; neither
process needs a public URL. Add the following shared variables to both services
(and add SMTP variables if tasks send email):

```text
DJANGO_SETTINGS_MODULE=plane.settings.production
SECRET_KEY=<the same stable API secret>
DATABASE_URL=<Neon pooled connection string>
DATABASE_CONN_MAX_AGE=0
REDIS_URL=<Upstash rediss:// connection string>
CELERY_BROKER_URL=<the same Upstash rediss:// connection string>
CELERY_RESULT_BACKEND=<the same Upstash rediss:// connection string>
AWS_REGION=auto
AWS_ACCESS_KEY_ID=<R2 key>
AWS_SECRET_ACCESS_KEY=<R2 secret>
AWS_S3_BUCKET_NAME=plane-uploads
AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
USE_MINIO=0
FILE_SIZE_LIMIT=5242880
SIGNED_URL_EXPIRATION=3600
```

Run migrations once before starting the services. The existing entrypoint scripts
wait for the database and migrations before launching Celery. Watch the worker
logs for a successful connection to Redis and the beat logs for the scheduled
`django-celery-beat` scheduler.

Northflank's free allowance and regions can change, so confirm the current
Sandbox limits before deployment. Two always-on services are enough for a demo,
but not for high-volume task queues or production redundancy.

### More reliable free infrastructure: Oracle Cloud Always Free VM

If Northflank is unavailable or its free limits do not fit, create an Oracle
Cloud Always Free Ubuntu VM. Oracle currently lists up to 2 OCPUs and 12 GB RAM
of Ampere A1 compute for Always Free tenancies, plus 200 GB total block storage.
Capacity can be unavailable in a region and idle instances can be reclaimed, so
this is free infrastructure with self-managed operational risk.

On the VM, build the API image and run two containers:

```bash
git clone https://github.com/el-naza/work-os.git /opt/work-os
cd /opt/work-os

# Create this file with chmod 600 and fill in real values.
install -d -m 700 /etc/plane
$EDITOR /etc/plane/worker.env
chmod 600 /etc/plane/worker.env

docker build -f apps/api/Dockerfile.api -t plane-api-worker apps/api

docker run -d --name plane-worker --restart unless-stopped \
  --env-file /etc/plane/worker.env \
  plane-api-worker ./bin/docker-entrypoint-worker.sh
docker run -d --name plane-beat --restart unless-stopped \
  --env-file /etc/plane/worker.env \
  plane-api-worker ./bin/docker-entrypoint-beat.sh
```

Do not use the repository's full `docker-compose.yml` for this small VM unless
Postgres, Redis, and the other services are intentionally being self-hosted;
that compose file is a complete local/container deployment. Keep Postgres on
Neon and Redis on Upstash for the split topology.

### Providers that are not genuinely free for this worker

- Render has a free web-service type, but its own documentation says there is no
  free instance type for Background Workers. A continuously running Render
  worker therefore starts on a paid instance.
- Koyeb's free instance is restricted to Web Services and explicitly cannot be a
  Worker Service.
- Railway's Free plan currently provides only $1 of monthly usage credit. It is
  useful for a short trial or a stopped-on-demand process, but not a reliable
  24/7 Celery worker at no cost.

## 6. Keep real-time collaboration separate

`apps/live` is an Express + Hocuspocus WebSocket server. Vercel and Netlify
request functions are not a suitable home for a long-lived WebSocket process.
Deploy it as a Docker/Node web service and set:

```text
PORT=<host-provided port>
API_BASE_URL=https://api.example.com
CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com,https://spaces.example.com
LIVE_BASE_PATH=/live
LIVE_SERVER_SECRET_KEY=<stable random secret>
REDIS_URL=<the same Upstash URL, or a dedicated Redis database>
```

A free instance can be acceptable for a demo, but sleeping services will cause
WebSocket disconnects and cold starts. A reliable collaboration experience
needs an always-on service and a Redis plan with enough connection/throughput
headroom.

## Environment and security checklist

- Generate and keep one stable, high-entropy `SECRET_KEY`; never use the
  placeholders from the examples.
- Use exact HTTPS origins in `CORS_ALLOWED_ORIGINS`; do not use `*` with
  credentialed cookies.
- Set `ALLOWED_HOSTS` to the API hostname rather than `*`.
- Set `CSRF_TRUSTED_ORIGINS` indirectly through the same HTTPS CORS origins
  used by this project.
- Never commit `.env`, provider credentials, or R2 keys.
- Use separate preview/staging databases and buckets. Do not point a deploy
  preview at production data.
- Add provider spending alerts even when starting on a free tier.
- Test file upload, password reset, OAuth callbacks, invitations, CSV/XLSX
  export, and WebSocket reconnects; these exercise different infrastructure
  paths.

## What this takes

### To get a demo online

About **2–4 hours** once the provider accounts and DNS access are available:

1. Create Neon, Upstash, R2, and email accounts (30–60 min).
2. Add environment variables and run migrations (30–60 min).
3. Deploy the API and three static sites (30–60 min).
4. Test sign-in, create a workspace, create an issue, and upload a file
   (30–60 min).

### To call it production-ready

Plan on **1–3 additional days** for domain/DNS, OAuth callback configuration,
email deliverability, CORS/CSRF review, backups, monitoring, provider limits,
and regression testing. The free tier is suitable for a small demo or internal
pilot, not a guaranteed always-on SaaS service.

### What is not a one-evening rewrite

A fully serverless-native rewrite of the backend would be a separate project:
Django currently has hundreds of API/task modules and assumes Postgres, Redis,
Celery, S3, and a persistent live server. Replacing that with edge functions,
managed auth, queue jobs, and database RPCs would take **multiple weeks** and
would risk changing application behavior. The included adapter deliberately
keeps the existing Django domain logic instead.

## Platform references

- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
- [Netlify Functions overview and supported languages](https://docs.netlify.com/build/functions/overview/)
- [Netlify Functions configuration](https://docs.netlify.com/build/functions/configuration/)
- [React Router SPA mode](https://reactrouter.com/how-to/spa)
- [Neon plans](https://neon.com/docs/introduction/plans)
- [Upstash Redis pricing](https://upstash.com/pricing)
- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [Resend pricing](https://resend.com/pricing)
- [Northflank pricing and Sandbox](https://northflank.com/pricing)
- [Oracle Cloud Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm)
- [Render background worker guidance](https://render.com/articles/cron-jobs-vs-background-workers-vs-durable-workflows-picking-the-right-async-pri)
- [Koyeb instance limitations](https://www.koyeb.com/docs/reference/instances)
- [Railway pricing plans](https://docs.railway.com/pricing/plans)
