import { serveReportArtifact } from "../../../../../../../lib/report-download";

export async function POST(
  request: Request,
  context: { params: Promise<{ reportId: string; artifactId: string }> },
) {
  const { reportId, artifactId } = await context.params;
  return serveReportArtifact(request, "reports", reportId, artifactId);
}
