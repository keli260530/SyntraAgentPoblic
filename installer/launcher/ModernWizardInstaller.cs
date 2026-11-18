using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Syntra Windows 安裝嚮導")]
[assembly: AssemblyProduct("Syntra")]
[assembly: AssemblyVersion("2.5.0.0")]

internal class ModernWizardForm : Form
{
    private Panel headerPanel;
    private Label titleLabel;
    private Label subtitleLabel;
    private Panel contentPanel;
    private Panel footerPanel;
    private Button btnBack;
    private Button btnNext;
    private Button btnCancel;

    private int currentStep = 0;

    private TextBox txtPath;
    private Panel pnlCoreItem;
    private CheckBox chkSecurityDlc;
    private CheckBox chkOfficeDlc;
    private TextBox txtLicenseKey;
    private ProgressBar progressBar;
    private Label lblStatus;
    private CheckBox chkLaunchNow;
    private CheckBox chkDesktopShortcut;

    private string installPath;

    public ModernWizardForm()
    {
        InitializeComponents();
        ShowStep(0);
    }

    private void InitializeComponents()
    {
        this.Text = "Syntra 安裝程式 (v2.5.0)";
        this.Size = new Size(580, 450);
        this.StartPosition = FormStartPosition.CenterScreen;
        this.FormBorderStyle = FormBorderStyle.FixedDialog;
        this.MaximizeBox = false;
        this.BackColor = Color.FromArgb(15, 18, 26);
        this.ForeColor = Color.White;
        this.Font = new Font("Microsoft JhengHei UI", 9.5F, FontStyle.Regular);

        // Header Panel
        headerPanel = new Panel
        {
            Dock = DockStyle.Top,
            Height = 72,
            BackColor = Color.FromArgb(24, 30, 44)
        };
        titleLabel = new Label
        {
            Text = "Syntra Agent 安裝嚮導",
            Font = new Font("Microsoft JhengHei UI", 12.5F, FontStyle.Bold),
            ForeColor = Color.White,
            Location = new Point(24, 13),
            AutoSize = true
        };
        subtitleLabel = new Label
        {
            Text = "輕量、安全、不干擾操作的多代理本機研發協作平台",
            Font = new Font("Microsoft JhengHei UI", 9F),
            ForeColor = Color.FromArgb(160, 175, 200),
            Location = new Point(25, 41),
            AutoSize = true
        };
        headerPanel.Controls.Add(titleLabel);
        headerPanel.Controls.Add(subtitleLabel);

        // Footer Panel
        footerPanel = new Panel
        {
            Dock = DockStyle.Bottom,
            Height = 56,
            BackColor = Color.FromArgb(24, 30, 44)
        };
        btnCancel = new Button
        {
            Text = "取消",
            Size = new Size(84, 32),
            Location = new Point(470, 11),
            FlatStyle = FlatStyle.Flat,
            BackColor = Color.FromArgb(40, 50, 70),
            ForeColor = Color.White
        };
        btnCancel.Click += (s, e) => { if (currentStep == 2) return; this.Close(); };

        btnNext = new Button
        {
            Text = "下一步 >",
            Size = new Size(95, 32),
            Location = new Point(365, 11),
            FlatStyle = FlatStyle.Flat,
            BackColor = Color.FromArgb(37, 99, 235),
            ForeColor = Color.White
        };
        btnNext.Click += (s, e) => OnNextClicked();

        btnBack = new Button
        {
            Text = "< 上一步",
            Size = new Size(84, 32),
            Location = new Point(275, 11),
            FlatStyle = FlatStyle.Flat,
            BackColor = Color.FromArgb(40, 50, 70),
            ForeColor = Color.White,
            Visible = false
        };
        btnBack.Click += (s, e) => { if (currentStep > 0 && currentStep != 2) ShowStep(currentStep - 1); };

        footerPanel.Controls.Add(btnBack);
        footerPanel.Controls.Add(btnNext);
        footerPanel.Controls.Add(btnCancel);

        contentPanel = new Panel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(25, 20, 25, 20),
            BackColor = Color.FromArgb(15, 18, 26)
        };

        this.Controls.Add(contentPanel);
        this.Controls.Add(footerPanel);
        this.Controls.Add(headerPanel);

        // 預設安裝至專屬目錄，絕不隨意散落在桌面
        installPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Syntra");
    }

    private void ShowStep(int step)
    {
        currentStep = step;
        contentPanel.Controls.Clear();

        if (step == 0)
        {
            titleLabel.Text = "歡迎使用 Syntra 安裝程式";
            subtitleLabel.Text = "選擇您要安裝 Syntra 的目標資料夾";
            btnBack.Visible = false;
            btnNext.Text = "下一步 >";
            btnNext.Enabled = true;

            Label lblIntro = new Label
            {
                Text = "安裝程式將在您的電腦上部署純淨版核心環境與桌面捷徑。\n檔案會統一整理在專用目錄中，桌面僅建立一個啟動捷徑：",
                Location = new Point(25, 20),
                Size = new Size(510, 48),
                ForeColor = Color.FromArgb(220, 230, 245)
            };

            Label lblPath = new Label
            {
                Text = "目標安裝路徑 (預設為個人應用目錄，免管理員權限)：",
                Location = new Point(25, 80),
                AutoSize = true,
                Font = new Font("Microsoft JhengHei UI", 9.5F, FontStyle.Bold),
                ForeColor = Color.White
            };

            txtPath = new TextBox
            {
                Text = installPath,
                Location = new Point(25, 106),
                Size = new Size(410, 26),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };
            txtPath.TextChanged += (s, e) => { installPath = txtPath.Text.Trim(); };

            Button btnBrowse = new Button
            {
                Text = "瀏覽...",
                Location = new Point(445, 105),
                Size = new Size(80, 28),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(51, 65, 85),
                ForeColor = Color.White
            };
            btnBrowse.Click += (s, e) =>
            {
                using (FolderBrowserDialog fbd = new FolderBrowserDialog())
                {
                    fbd.SelectedPath = installPath;
                    if (fbd.ShowDialog() == DialogResult.OK)
                    {
                        txtPath.Text = Path.Combine(fbd.SelectedPath, "Syntra");
                    }
                }
            };

            chkDesktopShortcut = new CheckBox
            {
                Text = "在桌面建立「Syntra」捷徑 (僅建立單一圖標)",
                Checked = true,
                Location = new Point(25, 158),
                AutoSize = true,
                ForeColor = Color.FromArgb(147, 197, 253),
                Font = new Font("Microsoft JhengHei UI", 9.5F, FontStyle.Bold)
            };

            contentPanel.Controls.Add(lblIntro);
            contentPanel.Controls.Add(lblPath);
            contentPanel.Controls.Add(txtPath);
            contentPanel.Controls.Add(btnBrowse);
            contentPanel.Controls.Add(chkDesktopShortcut);
        }
        else if (step == 1)
        {
            titleLabel.Text = "自訂 DLC 模組與授權啟用";
            subtitleLabel.Text = "勾選欲啟用的功能模組，若有 Ed25519 授權密鑰可在此貼上";
            btnBack.Visible = true;
            btnNext.Text = "開始安裝";
            btnNext.Enabled = true;

            Label lblDlc = new Label
            {
                Text = "請勾選欲安裝的組件模組：",
                Location = new Point(25, 12),
                AutoSize = true,
                Font = new Font("Microsoft JhengHei UI", 9.5F, FontStyle.Bold),
                ForeColor = Color.White
            };

            // 高對比 Core Item 卡片
            pnlCoreItem = new Panel
            {
                Location = new Point(25, 38),
                Size = new Size(500, 32),
                BackColor = Color.FromArgb(24, 36, 50)
            };
            Label lblCoreCheck = new Label
            {
                Text = "☑",
                Location = new Point(8, 6),
                AutoSize = true,
                ForeColor = Color.FromArgb(52, 211, 153),
                Font = new Font("Segoe UI", 11F, FontStyle.Bold)
            };
            Label lblCoreText = new Label
            {
                Text = "Syntra Pure Core 核心引擎 (多代理協同、本機大模型調度) [必要核心]",
                Location = new Point(32, 6),
                AutoSize = true,
                ForeColor = Color.FromArgb(52, 211, 153),
                Font = new Font("Microsoft JhengHei UI", 9.5F, FontStyle.Bold)
            };
            pnlCoreItem.Controls.Add(lblCoreCheck);
            pnlCoreItem.Controls.Add(lblCoreText);

            chkSecurityDlc = new CheckBox
            {
                Text = "🛡️ 官方資安盾 (Security Shield DLC · 本機防毒相容與進程守護)",
                Checked = true,
                Location = new Point(25, 78),
                Size = new Size(500, 26),
                ForeColor = Color.White,
                Font = new Font("Microsoft JhengHei UI", 9.5F)
            };

            chkOfficeDlc = new CheckBox
            {
                Text = "📊 辦公自動化流水線 (Office Flow DLC · Excel/Word/PDF 批次轉換)",
                Checked = false,
                Location = new Point(25, 108),
                Size = new Size(500, 26),
                ForeColor = Color.White,
                Font = new Font("Microsoft JhengHei UI", 9.5F)
            };

            Label lblKey = new Label
            {
                Text = "🔑 授權金鑰 / 兌換碼 (選填，可稍後在軟體內免費或自費兌換)：",
                Location = new Point(25, 146),
                AutoSize = true,
                Font = new Font("Microsoft JhengHei UI", 9.5F, FontStyle.Bold),
                ForeColor = Color.FromArgb(226, 232, 240)
            };

            txtLicenseKey = new TextBox
            {
                Location = new Point(25, 172),
                Size = new Size(500, 26),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.FromArgb(147, 197, 253),
                BorderStyle = BorderStyle.FixedSingle
            };

            Label lblKeyHint = new Label
            {
                Text = "若尚未購買可在官網取得免費社群版，留空將以標準社群模式啟動。",
                Location = new Point(25, 204),
                Size = new Size(500, 20),
                Font = new Font("Microsoft JhengHei UI", 8.5F),
                ForeColor = Color.FromArgb(148, 163, 184)
            };

            contentPanel.Controls.Add(lblDlc);
            contentPanel.Controls.Add(pnlCoreItem);
            contentPanel.Controls.Add(chkSecurityDlc);
            contentPanel.Controls.Add(chkOfficeDlc);
            contentPanel.Controls.Add(lblKey);
            contentPanel.Controls.Add(txtLicenseKey);
            contentPanel.Controls.Add(lblKeyHint);
        }
        else if (step == 2)
        {
            titleLabel.Text = "正在安裝 Syntra...";
            subtitleLabel.Text = "正在釋放檔案至專用目錄並建立桌面捷徑，請稍候";
            btnBack.Visible = false;
            btnNext.Enabled = false;
            btnCancel.Enabled = false;

            lblStatus = new Label
            {
                Text = "正在解壓核心模組...",
                Location = new Point(25, 55),
                Size = new Size(500, 25),
                ForeColor = Color.White
            };

            progressBar = new ProgressBar
            {
                Location = new Point(25, 90),
                Size = new Size(500, 24),
                Minimum = 0,
                Maximum = 100,
                Value = 20
            };

            contentPanel.Controls.Add(lblStatus);
            contentPanel.Controls.Add(progressBar);

            ThreadPool.QueueUserWorkItem(RunExtractionWork);
        }
        else if (step == 3)
        {
            titleLabel.Text = "Syntra 安裝完成！";
            subtitleLabel.Text = "所有檔案已妥善收納於專屬目錄，感謝您的使用";
            btnBack.Visible = false;
            btnNext.Text = "完成";
            btnNext.Enabled = true;
            btnCancel.Visible = false;

            Label lblDone = new Label
            {
                Text = "🎉 安裝成功！\n\n" +
                       "• 安裝路徑：" + installPath + "\n" +
                       "• 桌面已建立單一「Syntra」捷徑\n" +
                       "• 絕不隨意散落批次檔或額外檔案於桌面",
                Location = new Point(25, 30),
                Size = new Size(500, 100),
                ForeColor = Color.White
            };

            chkLaunchNow = new CheckBox
            {
                Text = "立即啟動 Syntra",
                Checked = true,
                Location = new Point(25, 150),
                AutoSize = true,
                Font = new Font("Microsoft JhengHei UI", 10F, FontStyle.Bold),
                ForeColor = Color.FromArgb(96, 165, 250)
            };

            contentPanel.Controls.Add(lblDone);
            contentPanel.Controls.Add(chkLaunchNow);
        }
    }

    private void OnNextClicked()
    {
        if (currentStep == 0) ShowStep(1);
        else if (currentStep == 1) ShowStep(2);
        else if (currentStep == 3)
        {
            if (chkLaunchNow != null && chkLaunchNow.Checked) LaunchSyntra();
            this.Close();
        }
    }

    private void RunExtractionWork(object state)
    {
        try
        {
            UpdateProgress("正在準備專屬目錄...", 25);
            if (!Directory.Exists(installPath)) Directory.CreateDirectory(installPath);

            Assembly asm = Assembly.GetExecutingAssembly();
            string resourceName = "Syntra.payload.zip";
            foreach (string n in asm.GetManifestResourceNames())
            {
                if (n.EndsWith(".zip", StringComparison.OrdinalIgnoreCase)) { resourceName = n; break; }
            }

            UpdateProgress("正在釋放程式與內建執行環境（不需要另外安裝 Python）...", 35);
            Installer.ExtractPayload(installPath, (done, total) =>
                UpdateProgress("正在釋放檔案... " + done + " / " + total, 35 + (int)(45L * done / Math.Max(1, total))));

            UpdateProgress("正在儲存配置與授權資訊...", 85);
            SaveConfiguration();

            if (chkDesktopShortcut != null && chkDesktopShortcut.Checked)
            {
                UpdateProgress("正在桌面建立單一「Syntra」捷徑...", 90);
                CreateDesktopShortcut();
            }

            UpdateProgress("安裝完成！", 100);
            Thread.Sleep(300);
            this.Invoke(new Action(() => ShowStep(3)));
        }
        catch (Exception ex)
        {
            this.Invoke(new Action(() =>
            {
                MessageBox.Show(this, "安裝發生錯誤: " + ex.Message, "安裝錯誤", MessageBoxButtons.OK, MessageBoxIcon.Error);
                btnCancel.Enabled = true;
            }));
        }
    }

    private void SaveConfiguration()
    {
        try
        {
            string configDir = Path.Combine(installPath, "data");
            if (!Directory.Exists(configDir)) Directory.CreateDirectory(configDir);
            // 不可寫入 settings.json：那是程式自己的設定檔，重裝時會蓋掉使用者的設定
            string configFile = Path.Combine(configDir, "install_config.json");

            string licenseKey = txtLicenseKey != null ? txtLicenseKey.Text.Trim() : "";
            bool secDlc = chkSecurityDlc != null && chkSecurityDlc.Checked;
            bool offDlc = chkOfficeDlc != null && chkOfficeDlc.Checked;

            StringBuilder sb = new StringBuilder();
            sb.AppendLine("{");
            sb.AppendLine("  \"install_version\": \"2.5.1\",");
            sb.AppendLine("  \"license_token\": \"" + licenseKey.Replace("\\", "").Replace("\"", "") + "\",");
            sb.AppendLine("  \"enabled_dlc\": [");
            List<string> dlcList = new List<string>();
            if (secDlc) dlcList.Add("\"security_shield\"");
            if (offDlc) dlcList.Add("\"office_flow\"");
            sb.AppendLine("    " + string.Join(",\n    ", dlcList.ToArray()));
            sb.AppendLine("  ]");
            sb.AppendLine("}");

            File.WriteAllText(configFile, sb.ToString(), Encoding.UTF8);
        }
        catch { }
    }

    private void CreateDesktopShortcut()
    {
        try
        {
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            // 桌面只建立單一捷徑，名稱乾淨叫做 Syntra.lnk
            string shortcutPath = Path.Combine(desktop, "Syntra.lnk");
            string targetExe = Path.Combine(installPath, "Syntra.exe");

            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType != null)
            {
                dynamic shell = Activator.CreateInstance(shellType);
                dynamic shortcut = shell.CreateShortcut(shortcutPath);
                shortcut.TargetPath = targetExe;
                shortcut.WorkingDirectory = installPath;
                shortcut.Description = "Syntra 桌面協作平台";
                string iconPath = Path.Combine(installPath, "assets", "gemini_icon.ico");
                if (File.Exists(iconPath)) shortcut.IconLocation = iconPath;
                else shortcut.IconLocation = targetExe;
                shortcut.Save();
            }
        }
        catch { }
    }

    private void LaunchSyntra()
    {
        try
        {
            string exePath = Path.Combine(installPath, "Syntra.exe");
            if (File.Exists(exePath))
            {
                Process.Start(new ProcessStartInfo(exePath) { WorkingDirectory = installPath, UseShellExecute = true });
            }
        }
        catch { }
    }

    private void UpdateProgress(string text, int val)
    {
        if (this.InvokeRequired)
        {
            this.Invoke(new Action(() => UpdateProgress(text, val)));
            return;
        }
        if (lblStatus != null) lblStatus.Text = text;
        if (progressBar != null) progressBar.Value = Math.Min(100, Math.Max(0, val));
    }
}

internal static class Installer
{
    // 重裝／更新時不覆蓋的使用者資料（第一次安裝才寫入）
    private static readonly string[] KeepIfExists = { "data/mcp_servers.json" };

    public static void ExtractPayload(string installPath, Action<int, int> progress)
    {
        Assembly asm = Assembly.GetExecutingAssembly();
        string resourceName = null;
        foreach (string n in asm.GetManifestResourceNames())
            if (n.EndsWith(".zip", StringComparison.OrdinalIgnoreCase)) { resourceName = n; break; }
        if (resourceName == null) throw new InvalidOperationException("安裝程式內找不到程式封包");

        string root = Path.GetFullPath(installPath).TrimEnd('\\') + "\\";
        using (Stream stream = asm.GetManifestResourceStream(resourceName))
        using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read))
        {
            int total = zip.Entries.Count, done = 0;
            foreach (ZipArchiveEntry entry in zip.Entries)
            {
                done++;
                string rel = entry.FullName.Replace('\\', '/');
                string target = Path.GetFullPath(Path.Combine(root, rel));
                if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase)) continue;  // 防止路徑跳脫
                if (rel.EndsWith("/")) { Directory.CreateDirectory(target); continue; }
                if (Array.IndexOf(KeepIfExists, rel) >= 0 && File.Exists(target)) continue;
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                entry.ExtractToFile(target, true);
                if (progress != null && (done % 200 == 0 || done == total)) progress(done, total);
            }
        }
    }
}

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        // 靜默安裝：Syntra_Setup.exe /S [/D=安裝路徑]（給測試與企業部署用）
        bool silent = false;
        string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Syntra");
        foreach (string a in args)
        {
            if (a.Equals("/S", StringComparison.OrdinalIgnoreCase)) silent = true;
            else if (a.StartsWith("/D=", StringComparison.OrdinalIgnoreCase)) dir = a.Substring(3).Trim('"');
        }
        if (silent)
        {
            try { Directory.CreateDirectory(dir); Installer.ExtractPayload(dir, null); return 0; }
            catch (Exception ex) { Console.Error.WriteLine(ex.ToString()); return 1; }
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new ModernWizardForm());
        return 0;
    }
}
