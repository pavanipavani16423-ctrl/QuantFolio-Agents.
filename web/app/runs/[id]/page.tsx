import { RunView } from "@/components/run/run-view";

export const metadata = { title: "Run" };

export default async function RunPage({ params }: PageProps<"/runs/[id]">) {
  const { id } = await params;
  return <RunView id={id} />;
}
