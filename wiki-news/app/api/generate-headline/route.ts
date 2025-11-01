import { NextResponse } from 'next/server';
import { Ollama } from 'ollama'; 
const ollama = new Ollama({ host: 'http://localhost:11434' });

export async function POST(request: Request) {
  try {
    const { title, user, comment } = await request.json();

    // 1. Create a good prompt for the LLM
    const prompt = `
    You are a news editor. Based on the following real-time Wikipedia edit, 
    write one compelling, short news headline (under 12 words).
    Do not use quotes.

    - Article Title: ${title}
    - User: ${user || 'Anonymous'}
    - Edit Comment: ${comment || 'No comment'}

    Headline:
    `;

    // 2. Call Ollama
    const response = await ollama.chat({
      model: 'llama3.2:1b', // Make sure you have this model
      messages: [{ role: 'user', content: prompt }],
      stream: false,
    });

    const headline = response.message.content.trim().replace(/"/g, '');

    // 3. Send the headline back to the React app
    return NextResponse.json({ headline: headline });

  } catch (error) {
    console.error('Ollama API error:', error);
    return NextResponse.json(
      { error: 'Failed to get response from LLM' },
      { status: 500 }
    );
  }
}