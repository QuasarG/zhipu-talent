import { useState } from "react";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Progress from "@/components/ui/Progress";
import { useI18n } from "@/lib/i18n";

interface Props {
  confirmed: number;
  total: number;
  onConfirm: () => void;
  onClose: () => void;
}

/** 「提交给 HR 团队」确认弹窗：演示环境不真实发送，确认后只显示假成功态 */
export default function SubmitDialog({ confirmed, total, onConfirm, onClose }: Props) {
  const { t } = useI18n();
  const [done, setDone] = useState(false);
  const pct = total ? Math.round((confirmed / total) * 100) : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/40 p-6"
      onClick={onClose}
    >
      <Card
        variant="elevated"
        className="w-full max-w-md rounded-xl p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {done ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <Icon name="check_circle" size={40} fill className="text-success" />
            <h2 className="text-title-lg">{t("已提交给 HR 团队")}</h2>
            <p className="text-body-sm text-on-surface-variant">
              {t("演示环境，不会真实发送；HR 同事将收到这份画像与招聘需求包。")}
            </p>
            <Button variant="filled" className="mt-2" onClick={onClose}>
              {t("完成")}
            </Button>
          </div>
        ) : (
          <>
            <h2 className="text-title-lg">{t("提交给 HR 团队？")}</h2>
            <p className="mt-2 text-body-sm text-on-surface-variant">
              {t("提交前请确认右侧画像卡中的需求已澄清完整；提交后将把画像与招聘需求包发送给 HR 团队（演示环境，不会真实发送）。")}
            </p>
            <div className="mt-4 rounded-md bg-surface-low p-3">
              <div className="flex items-center justify-between text-label text-on-surface-variant">
                <span>{t("画像确认进度")}</span>
                <span>
                  {t("硬性门槛已确认 {confirmed}/{total}", { confirmed, total })}
                </span>
              </div>
              <Progress value={pct} className="mt-1.5" />
              {confirmed < total && (
                <p className="mt-1.5 flex items-center gap-1 text-label text-warning">
                  <Icon name="warning" size={14} />
                  {t("还有 {n} 项硬性门槛未确认，建议继续澄清", { n: total - confirmed })}
                </p>
              )}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="text" onClick={onClose}>
                {t("再想想")}
              </Button>
              <Button variant="filled" icon="send" onClick={() => { setDone(true); onConfirm(); }}>
                {t("确认提交")}
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
