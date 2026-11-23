import { CardView } from "./CardView";

export default async function CardPage({ params }: { params: Promise<{ slug: string; secret: string }> }) {
  const { slug, secret } = await params;
  return <CardView slug={slug} secret={secret} />;
}

export const metadata = { referrer: "no-referrer" };
