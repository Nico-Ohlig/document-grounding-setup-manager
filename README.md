# Document Grounding Setup Manager

Small self-hosted web UI that makes setting up SAP BTP Document Grounding easier.
It fetches OAuth2 bearer tokens via X.509 mTLS from a service key, helps you build the
SharePoint destination JSON, and lets you create, trigger, schedule and monitor document
grounding pipelines without hand-crafting curl commands.

This is an independent community project, not affiliated with or endorsed by SAP SE.
SAP, SAP BTP and Joule are trademarks of SAP SE.

## Prerequisites

Set up Joule document grounding as described in the official SAP guide
[Configure User Authentication](https://help.sap.com/docs/joule/integrating-joule-with-sap/configure-user-authentication?locale=en-US),
up to step 16.

From there, this tool takes over: instead of assembling the certificates by hand, just
download the service key of your Cloud Identity Services instance and the service binding
of your Document Grounding instance as JSON files and upload them to the tool.


## What it does

- Upload a Cloud Identity service key (`credential-type: X509_GENERATED`) and get a
  bearer token with one click
- Create SharePoint and WorkZone pipelines, trigger them (full or metadata-only),
  delete them
- Edit the pipeline cron schedule with presets (every X hours, daily, weekly, monthly)
  or a raw cron expression, with live preview
- List pipelines, browse documents and executions
- Generate the destination JSON for the BTP Destination service
- Inspect every request the tool sends (endpoint, body, raw response) and copy
  equivalent curl commands

Certificates are written to temp files only for the duration of a single request and
deleted right after. Nothing is persisted on the server, and the browser keeps
credentials in memory only.

## Running it

You need Python 3.8+ and a BTP subaccount with a Document Grounding service instance.

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5001, upload your Cloud Identity service key and the Document
Grounding service binding, done. Use the `PORT` env variable if 5001 is taken.

## Deploying to Cloud Foundry

```bash
mbt build
cf deploy mta_archives/document-grounding-setup-manager_1.0.0.mtar
```

or use the Included built version in mta_archives

There is no authentication built in. If you deploy this anywhere public, put it behind
an AppRouter or similar.

## Notes on cron schedules

Schedules use plain 5-field cron (`minute hour day-of-month month day-of-week`),
e.g. `0 3 * * *` for daily at 03:00 UTC. Two things to be aware of:

- SAP requires an interval greater than one hour. The UI warns you if you go below that.
- The pipeline API does not return the cron expression when you read a pipeline, only
  an `isCronEnabled` flag. So the tool can show *that* a schedule is active, but not
  *which* one, unless you just saved it.

## License

Apache 2.0, see [LICENSE](LICENSE).
