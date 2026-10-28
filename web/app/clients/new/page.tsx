import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { NewClientForm } from "@/components/clients/new-client-form";
import { Accent, SectionHeading } from "@/components/ui";

export default function NewClientPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
      <Link href="/" className="mb-6 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Back
      </Link>
      <SectionHeading
        eyebrow="New client"
        title={
          <>
            Add a client and <Accent>their rules</Accent>.
          </>
        }
        lead="Fill in who the client is, what they own and the limits they set. The agents follow these rules in every plan."
      />
      <div className="mt-8">
        <NewClientForm />
      </div>
    </div>
  );
}
