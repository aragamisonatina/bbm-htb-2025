import { NextResponse } from 'next/server';
import { Ollama } from 'ollama'; 
const ollama = new Ollama({ host: 'http://localhost:11434' });

export async function POST(request: Request) {
  try {
    const { title, user, comment } = await request.json();

    const prompt = `
    You are a news editor. Based on the following real-time Wikipedia edit, 
    write one compelling, short news headline (under 12 words).
    Do not use quotes.

    - Article Title: ${title}
    - Edit Comment: ${comment || 'No comment'}

    Your response MUST be the headline text and nothing else.
    Do not include "Here's a headline:" or any other explanatory text.
    `;

    const response = await ollama.chat({
      model: 'llama3.2:1b',
      messages: [{ role: 'user', content: prompt }],
      stream: false,
    });

    const headline = response.message.content.trim().replace(/"/g, '');

    return NextResponse.json({ headline: headline });

  } catch (error) {
    console.error('Ollama API error:', error);
    return NextResponse.json(
      { error: 'Failed to get response from LLM' },
      { status: 500 }
    );
  }
}