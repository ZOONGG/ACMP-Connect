import { defineRailway, project, service, volume } from "railway/iac";

// Source and secret variables are configured privately in Railway.
// Review the plan before apply: this declares a billable service and volume.
export default defineRailway(() => {
  const data = volume("acmp-data", { region: "europe-west4", sizeMB: 1024 });
  const server = service("acmp-connect", {
    start: "python -m acmp_connect.container_entrypoint",
    replicas: 1,
    healthcheck: "/healthz",
    healthcheckTimeout: 60,
    volumeMounts: { "/data": data },
    env: { DATABASE_PATH: "/data/acmp.sqlite3", ACMP_DEV: "0" },
  });
  return project("acmp-connect", { resources: [server, data] });
});
