/**
 * Firm-side "Profile" tab for a client. Shows the same editable form the
 * client portal sees, so the firm can pre-fill or correct it.
 */
import ClientProfileForm from "../../components/ClientProfileForm";

export default function ProfileTab({
  clientId,
  clientName,
}: {
  clientId: string;
  clientName?: string;
}) {
  return (
    <ClientProfileForm
      clientId={clientId}
      clientName={clientName}
      audience="firm"
    />
  );
}
