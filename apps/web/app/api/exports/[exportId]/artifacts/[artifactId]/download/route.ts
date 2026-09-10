import { serveReportArtifact } from "../../../../../../../lib/report-download";

export async function POST(
  request: Request,
  context: { params: Promise<{ exportId: string; artifactId: string }> },
) {
  const { exportId, artifactId } = await context.params;
  return serveReportArtifact(request, "exports", exportId, artifactId);
}
