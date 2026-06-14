import { LandhausStatusPanel } from '../components/landhaus/LandhausStatusPanel';

export function LandhausPage() {
  return (
    <div className="flex flex-col h-full overflow-auto p-4 md:p-6">
      <LandhausStatusPanel />
    </div>
  );
}
